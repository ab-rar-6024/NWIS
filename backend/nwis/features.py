"""Feature engineering shared by model training and live inference."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .analytics import weight
from .config import RISK_TYPES
from .kb import KnowledgeIndex, Trajectory

WINDOW_M = 60.0  # stratigraphic window for offset-event lookups
OFFSET_RADIUS_KM = 8.0
LIVE_COLS = ["rop", "wob", "rpm", "torque", "spp", "flow_in", "flow_out", "pit_delta", "mw", "gas", "overpull"]

GEO_FEATURES = ["md", "tvd", "inc", "fm_idx", "depth_in_fm", "off_density", "nearest_off_km"]
OFFSET_FEATURES = [f"off_{k}_{t}" for t in RISK_TYPES for k in ("near", "ahead")]
LIVE_FEATURES = [
    "rop", "wob", "rpm", "torque", "spp", "flow_diff_pct", "pit_delta", "pit_d3", "gas", "overpull", "mw",
    "torque_ratio", "rop_ratio", "gas_delta", "overpull_delta", "flow_diff_max2", "spp_delta", "mse", "mse_ratio",
]
ALL_FEATURES = GEO_FEATURES + OFFSET_FEATURES + LIVE_FEATURES

DEFAULT_HOLE_IN = 12.25  # fallback bit size when a well's casing programme isn't known yet (~standard intermediate hole)
MSE_CAP_MPA = 800.0  # sane physical ceiling (real field MSE rarely exceeds ~100,000 psi / 690 MPa); guards against noise spikes


def teale_mse_mpa(wob_t, rpm, torque_knm, rop_mph, hole_in) -> np.ndarray:
    """Teale's Mechanical Specific Energy: the energy spent per unit volume of rock drilled (MPa).

    MSE = axial term (WOB / bit area) + rotary term (2*pi*RPS*torque / (bit area * ROP)). It rises when a lot of
    effort produces little progress — a real, named drilling-engineering diagnostic for bit wear, formation
    change, and inefficient/stuck-pipe-prone drilling, computed here from first principles in SI units rather
    than an imperial "field units" shortcut formula, then reported in MPa (1 MPa ~= 145 psi).
    """
    wob_t = np.asarray(wob_t, float)
    rpm = np.asarray(rpm, float)
    torque_knm = np.asarray(torque_knm, float)
    rop_mph = np.asarray(rop_mph, float)
    if hole_in is None:
        hole_in = DEFAULT_HOLE_IN
    hole_arr = np.nan_to_num(np.asarray(hole_in, float), nan=DEFAULT_HOLE_IN)
    hole_arr = np.where(hole_arr <= 0, DEFAULT_HOLE_IN, hole_arr)

    area_m2 = np.pi * (hole_arr * 0.0254 / 2) ** 2
    wob_n = wob_t * 1000.0 * 9.80665
    torque_nm = torque_knm * 1000.0
    n_rps = rpm / 60.0
    rop_mps = np.clip(rop_mph, 1.0, None) / 3600.0

    axial_pa = wob_n / area_m2
    rotary_pa = (2 * np.pi * n_rps * torque_nm) / (area_m2 * rop_mps)
    mse_mpa = (axial_pa + rotary_pa) / 1e6
    return np.clip(mse_mpa, 0.0, MSE_CAP_MPA)


def z_of_tvd(tvd: np.ndarray, tops: list[dict], ref_tops: dict[str, float]):
    """Vectorised stratigraphic-depth mapping. Returns (z, fm_idx, depth_in_fm)."""
    tvd = np.asarray(tvd, float)
    if not tops:
        return tvd.copy(), np.zeros(len(tvd)), tvd.copy()
    tt = np.array([t["tvd"] for t in tops])
    idx = np.searchsorted(tt, tvd, side="right") - 1
    z = tvd.copy()
    fm_idx = np.zeros(len(tvd))
    dif = np.zeros(len(tvd))
    order = {f: i for i, f in enumerate(sorted(ref_tops, key=ref_tops.get))}
    for i, t in enumerate(tops):
        m = idx == i
        if not m.any():
            continue
        ref = ref_tops.get(t["formation"])
        dif[m] = tvd[m] - t["tvd"]
        z[m] = (ref + dif[m]) if ref is not None else tvd[m]
        fm_idx[m] = order.get(t["formation"], -1)
    return z, fm_idx, dif


class OffsetContext:
    """Pre-computed offset-well information for one target well (real or planned)."""

    def __init__(self, kb: KnowledgeIndex, target: Trajectory, tops: list[dict], radius_km: float = OFFSET_RADIUS_KM):
        self.kb = kb
        self.target = target
        self.tops = tops
        self.offsets = []
        for t, d in kb.nearby(target, radius_km):
            zs: dict[str, np.ndarray] = {}
            for et in RISK_TYPES:
                z = sorted(e["z"] for e in kb.events_by_well.get(t.id, []) if e["type"] == et and e["z"] is not None)
                zs[et] = np.array(z, float)
            self.offsets.append((t, d, zs))

    def features(self, md: np.ndarray, tvd: np.ndarray, z_jitter: np.ndarray | None = None) -> pd.DataFrame:
        kb, tg = self.kb, self.target
        z_s, fm_idx, dif = z_of_tvd(tvd, self.tops, kb.ref_tops)
        if z_jitter is not None:
            z_s = z_s + z_jitter
        n = len(md)
        es = np.array([tg.pos_at_md(m) for m in md]) if n else np.zeros((0, 2))
        num = {(k, t): np.zeros(n) for t in RISK_TYPES for k in ("near", "ahead")}
        den = np.zeros(n)
        nearest = np.full(n, 99.0)
        for t, _, zs in self.offsets:
            e_o = t.east0 + np.interp(tvd, t.tvd, t.e_m) / 1000.0
            n_o = t.north0 + np.interp(tvd, t.tvd, t.n_m) / 1000.0
            dist = np.hypot(es[:, 0] - e_o, es[:, 1] - n_o)
            pen = (t.td_tvd >= tvd - 10).astype(float)
            w = np.array([weight(x) for x in dist]) * pen
            den += w
            nearest = np.where(pen > 0, np.minimum(nearest, dist), nearest)
            for et in RISK_TYPES:
                zv = zs[et]
                if len(zv) == 0:
                    continue
                near = np.searchsorted(zv, z_s + WINDOW_M, "right") - np.searchsorted(zv, z_s - WINDOW_M, "left")
                ahead = np.searchsorted(zv, z_s + WINDOW_M, "right") - np.searchsorted(zv, z_s, "left")
                num[("near", et)] += w * near
                num[("ahead", et)] += w * ahead
        cols = {"depth_in_fm": dif, "fm_idx": fm_idx, "off_density": np.log1p(den), "nearest_off_km": np.minimum(nearest, 20.0)}
        safe = np.where(den > 0, den, 1.0)
        for (k, et), v in num.items():
            cols[f"off_{k}_{et}"] = np.where(den > 0, v / safe, 0.0)
        return pd.DataFrame(cols)


def live_features(df: pd.DataFrame, hole_in=None) -> pd.DataFrame:
    """Signal features from drilling parameters (df sorted by md, columns LIVE_COLS).

    `hole_in`: current bit/hole diameter per row (from the well's casing programme), used for the Mechanical
    Specific Energy calculation; falls back to a standard intermediate-hole default when the casing programme
    isn't known yet (e.g. a well with no completion report).
    """
    out = pd.DataFrame(index=df.index)
    for c in ("rop", "wob", "rpm", "torque", "spp", "pit_delta", "gas", "overpull", "mw"):
        out[c] = df[c].values
    flow_diff = (df["flow_out"] - df["flow_in"]) / df["flow_in"].clip(lower=1) * 100
    out["flow_diff_pct"] = flow_diff.values
    out["pit_d3"] = (df["pit_delta"] - df["pit_delta"].shift(3)).fillna(0.0).values

    def ratio(s, w=9):
        base = s.rolling(w, min_periods=3).median().shift(1)
        return (s / base.clip(lower=1e-6)).fillna(1.0)

    def delta(s, w=9):
        base = s.rolling(w, min_periods=3).median().shift(1)
        return (s - base).fillna(0.0)

    out["torque_ratio"] = ratio(df["torque"]).values
    out["rop_ratio"] = ratio(df["rop"]).values
    out["gas_delta"] = delta(df["gas"]).values
    out["overpull_delta"] = delta(df["overpull"]).values
    out["spp_delta"] = delta(df["spp"]).values
    out["flow_diff_max2"] = flow_diff.rolling(2, min_periods=1).max().values
    mse = teale_mse_mpa(df["wob"], df["rpm"], df["torque"], df["rop"], hole_in)
    out["mse"] = mse
    out["mse_ratio"] = ratio(pd.Series(mse, index=df.index)).values
    return out


def build_feature_frame(ctx: OffsetContext, logs: pd.DataFrame, z_jitter: np.ndarray | None = None) -> pd.DataFrame:
    logs = logs.sort_values("md").reset_index(drop=True)
    geo = ctx.features(logs["md"].values, logs["tvd"].values, z_jitter)
    geo["md"] = logs["md"].values
    geo["tvd"] = logs["tvd"].values
    geo["inc"] = logs["inc"].values
    hole_in = ctx.target.hole_diameter_at_md_arr(logs["md"].values)
    live = live_features(logs, hole_in)
    return pd.concat([geo.reset_index(drop=True), live.reset_index(drop=True)], axis=1)[ALL_FEATURES]
