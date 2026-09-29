"""Gradient-boosted drilling-risk models: probability of each hazard within the next LOOKAHEAD_M metres."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupKFold

from .analytics import predict_tops  # noqa: F401  (re-exported for convenience)
from .config import LOOKAHEAD_M, MODEL_DIR, RISK_TYPES
from .features import ALL_FEATURES, GEO_FEATURES, LIVE_FEATURES, OFFSET_FEATURES, LIVE_COLS, OffsetContext, build_feature_frame
from .kb import KnowledgeIndex

MODEL_PATH = MODEL_DIR / "risk_model.joblib"
METRICS_PATH = MODEL_DIR / "risk_model_metrics.json"
BEHIND_M = 10.0  # an event this close behind the bit still counts as "at" the sample
STRIDE = 2


def load_logs(conn: sqlite3.Connection, well_id: int) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT md, tvd, inc, rop, wob, rpm, torque, spp, flow_in, flow_out, pit_delta, mw, gas, overpull FROM drilling_logs WHERE well_id=? ORDER BY md",
        conn, params=(well_id,))


def make_labels(md: np.ndarray, events: list[dict], etype: str) -> np.ndarray:
    ev = np.sort([e["md"] for e in events if e["type"] == etype])
    if len(ev) == 0:
        return np.zeros(len(md), int)
    lo = np.searchsorted(ev, md - BEHIND_M, "left")
    hi = np.searchsorted(ev, md + LOOKAHEAD_M, "right")
    return (hi > lo).astype(int)


def build_training_set(kb: KnowledgeIndex, conn: sqlite3.Connection, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for wid, tr in kb.traj.items():
        if (tr.status or "").upper() == "ACTIVE" or not tr.tops:
            continue
        logs = load_logs(conn, wid)
        if logs.empty:
            continue
        ctx = OffsetContext(kb, tr, tr.tops)  # leave-one-well-out: nearby() never returns the target itself
        jitter = rng.normal(0, 15.0, len(logs))  # emulate top-prediction error seen at inference time
        X = build_feature_frame(ctx, logs, jitter)
        evs = kb.events_by_well.get(wid, [])
        for et in RISK_TYPES:
            X[f"y_{et}"] = make_labels(logs["md"].values, evs, et)
        X["well_id"] = wid
        frames.append(X.iloc[::STRIDE])
    return pd.concat(frames, ignore_index=True)


def _new_clf() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=180, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=25,
                                          l2_regularization=1.0, random_state=0)


def _best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-9, None)
    if len(thr) == 0:
        return 0.3
    return float(np.clip(thr[int(np.nanargmax(f1[:-1]))], 0.12, 0.6))


def cross_validate(df: pd.DataFrame, feature_sets: dict[str, list[str]], folds: int = 5) -> dict:
    gkf = GroupKFold(n_splits=folds)
    res: dict = {}
    for name, feats in feature_sets.items():
        res[name] = {}
        for et in RISK_TYPES:
            y = df[f"y_{et}"].values
            oof = np.zeros(len(df))
            for tr, te in gkf.split(df, y, df["well_id"]):
                clf = _new_clf().fit(df.iloc[tr][feats], y[tr])
                oof[te] = clf.predict_proba(df.iloc[te][feats])[:, 1]
            res[name][et] = {
                "auc": float(roc_auc_score(y, oof)), "ap": float(average_precision_score(y, oof)),
                "base_rate": float(y.mean()), "threshold": _best_threshold(y, oof),
            }
    return res


def train(conn: sqlite3.Connection, kb: KnowledgeIndex | None = None, ablation: bool = True, log=print) -> dict:
    t0 = time.time()
    kb = kb or KnowledgeIndex(conn)
    df = build_training_set(kb, conn)
    log(f"training set: {len(df)} samples from {df['well_id'].nunique()} wells, {len(ALL_FEATURES)} features")
    sets = {"full": ALL_FEATURES}
    if ablation:
        sets["offset_knowledge_only"] = GEO_FEATURES + OFFSET_FEATURES
        sets["live_signals_only"] = GEO_FEATURES[:3] + LIVE_FEATURES
    cv = cross_validate(df, sets)
    models = {}
    for et in RISK_TYPES:
        models[et] = _new_clf().fit(df[ALL_FEATURES], df[f"y_{et}"].values)
    thresholds = {et: cv["full"][et]["threshold"] for et in RISK_TYPES}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "features": ALL_FEATURES, "thresholds": thresholds}, MODEL_PATH)
    metrics = {
        "n_samples": int(len(df)), "n_wells": int(df["well_id"].nunique()), "horizon_m": LOOKAHEAD_M,
        "cv": "5-fold, grouped by well (no well appears in both train and test); offset features are leave-one-well-out",
        "results": cv, "thresholds": thresholds, "trained_seconds": round(time.time() - t0, 1),
        "data_note": "Metrics are measured on SYNTHETIC data with hazards generated from known spatial rules; they demonstrate the "
                     "pipeline, not real-world accuracy.",
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    return metrics


class RiskModel:
    def __init__(self, path: Path = MODEL_PATH):
        blob = joblib.load(path)
        self.models: dict = blob["models"]
        self.features: list[str] = blob["features"]
        self.thresholds: dict = blob["thresholds"]

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        X = X[self.features]
        return {et: m.predict_proba(X)[:, 1] for et, m in self.models.items()}


def model_available() -> bool:
    return MODEL_PATH.exists()


def load_metrics() -> dict | None:
    return json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None
