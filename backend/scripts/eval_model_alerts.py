"""Operating-point evaluation of the risk model: precision, recall and false alarms *per well*, not per sample.

AUC on a 1% base-rate hazard looks impressive and hides the number that actually matters to a driller: how
many times would this thing cry wolf on a single well? This script reuses the same grouped cross-validation
as train_model.py, thresholds the out-of-fold probabilities exactly as the live alert engine does, collapses
consecutive positive samples into "alert episodes" (an episode is one alert, not one sample), and checks each
episode against the well's own recorded events.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.config import RISK_TYPES
from nwis.db import connect
from nwis.kb import KnowledgeIndex
from nwis.risk_model import _new_clf, build_training_set, load_metrics

MATCH_TOL_M = 60.0  # an episode within this many metres of a real event of the same type counts as a hit
EPISODE_GAP_M = 30.0  # positive samples closer than this (at STRIDE=2, ~10 m/sample) merge into one episode


def episodes(md: np.ndarray, positive: np.ndarray) -> list[tuple[float, float]]:
    out = []
    start = None
    last = None
    for m, p in zip(md, positive):
        if p:
            if start is None:
                start = m
            elif last is not None and m - last > EPISODE_GAP_M:
                out.append((start, last))
                start = m
            last = m
        elif start is not None:
            out.append((start, last))
            start = None
    if start is not None:
        out.append((start, last))
    return out


def main() -> None:
    conn = connect()
    kb = KnowledgeIndex(conn)
    df = build_training_set(kb, conn)
    metrics = load_metrics()
    wells = {v["id"]: v for v in kb.wells.values()}
    id_to_name = {v["id"]: v["name"] for v in kb.wells.values()}

    print(f"{'hazard':16s} {'thr':>5s} | {'episodes/well':>13s} {'false/well':>10s} | {'events':>7s} {'event recall':>12s} {'episode precision':>18s}")
    for et in RISK_TYPES:
        thr = metrics["thresholds"][et]
        y = df[f"y_{et}"].values
        oof = np.zeros(len(df))
        gkf = GroupKFold(n_splits=5)
        feats = [c for c in df.columns if not c.startswith("y_") and c != "well_id"]
        for tr, te in gkf.split(df, y, df["well_id"]):
            clf = _new_clf().fit(df.iloc[tr][feats], y[tr])
            oof[te] = clf.predict_proba(df.iloc[te][feats])[:, 1]
        df["_p"] = oof
        df["_pos"] = oof >= thr

        n_episodes = n_false = n_true_hits = 0
        total_events = 0
        events_hit = 0
        for wid, g in df.groupby("well_id"):
            g = g.sort_values("md")
            eps = episodes(g["md"].values, g["_pos"].values)
            truth = [e["md"] for e in kb.events_by_well.get(wid, []) if e["type"] == et]
            total_events += len(truth)
            hit_truth = set()
            for a, b in eps:
                n_episodes += 1
                matched = [t for t in truth if a - MATCH_TOL_M <= t <= b + MATCH_TOL_M]
                if matched:
                    n_true_hits += 1
                    hit_truth.update(matched)
                else:
                    n_false += 1
            events_hit += len(hit_truth)
        n_wells = df["well_id"].nunique()
        recall = events_hit / total_events if total_events else float("nan")
        precision = n_true_hits / n_episodes if n_episodes else float("nan")
        print(f"{et:16s} {thr:5.2f} | {n_episodes / n_wells:13.2f} {n_false / n_wells:10.2f} | "
              f"{total_events:7d} {recall:12.1%} {precision:18.1%}")


if __name__ == "__main__":
    main()
