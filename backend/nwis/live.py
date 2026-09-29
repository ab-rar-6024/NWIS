"""Live monitoring: consumes eRTMAC-style samples (replayed from CSV or pushed via API) and raises alerts.

Alert families
- lookahead : offset wells had this hazard at the equivalent depth within the next ALERT_LOOKAHEAD_M metres
- formation : entering a formation with elevated historical NPT
- realtime  : rule-based anomaly detection on the incoming signals (influx, losses, torque/overpull trend, drilling break)
- model     : gradient-boosted probability of a hazard within LOOKAHEAD_M crossed its threshold
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .analytics import as_trajectory_tops, hazard_zones, predict_tops, risk_profile
from .config import ALERT_LOOKAHEAD_M, EVENT_LABELS, RAW_DIR, RISK_TYPES
from .db import j
from .features import LIVE_COLS, OffsetContext, build_feature_frame, teale_mse_mpa
from .kb import KnowledgeIndex
from .risk_model import RiskModel, model_available

HIST_ROWS = 60
FORMATION_ALERT_AHEAD_M = 150.0
MODEL_REARM_M = 60.0


@dataclass
class LiveSession:
    kb: KnowledgeIndex
    conn: sqlite3.Connection
    well_id: int
    radius_km: float = 8.0
    model: RiskModel | None = None
    replay: pd.DataFrame | None = None
    speed: float = 8.0
    running: bool = False
    idx: int = 0
    start_md: float = 1300.0
    history: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.tr = self.kb.traj[self.well_id]
        self.name = self.kb.wells[self.well_id]["name"]
        self.subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        if self.model is None and model_available():
            self.model = RiskModel()
        if self.replay is None:
            p = RAW_DIR / self.name / "replay_logs.csv"
            self.replay = pd.read_csv(p) if p.exists() else pd.DataFrame()
        self.prepare()

    # ------------------------------------------------------------------ setup
    def prepare(self) -> None:
        self.pred_tops = predict_tops(self.kb, self.tr, self.radius_km)
        self.ctx = OffsetContext(self.kb, self.tr, as_trajectory_tops(self.pred_tops), self.radius_km)
        self.zones = hazard_zones(self.kb, self.tr, self.pred_tops, 0.0, self.tr.td_md, self.radius_km, min_prevalence=0.12)
        self.profile = risk_profile(self.kb, self.tr, self.pred_tops, self.radius_km)
        self.reset()

    def reset(self, start_md: float | None = None) -> None:
        if start_md is not None:
            self.start_md = start_md
        self.running = False
        self.history = []
        self.alerts = []
        self._zone_alerted: set[str] = set()
        self._fm_alerted: set[str] = set()
        self._last_model_alert: dict[str, float] = {}
        self._model_armed = {t: True for t in RISK_TYPES}
        self._last_rt: dict[str, float] = {}
        self.probs: dict[str, float] = {t: 0.0 for t in RISK_TYPES}
        self.conn.execute("DELETE FROM alerts WHERE well_id=?", (self.well_id,))
        self.conn.commit()
        if len(self.replay):
            self.idx = int(np.searchsorted(self.replay["md"].values, self.start_md))
        else:
            self.idx = 0

    # ------------------------------------------------------------------ pub/sub
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def publish(self, kind: str, payload: dict) -> None:
        msg = json.dumps({"type": kind, "data": payload}, default=float)
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def state(self) -> dict:
        md = self.history[-1]["md"] if self.history else None
        return {"running": self.running, "speed": self.speed, "idx": self.idx, "n": int(len(self.replay)), "md": md,
                "start_md": self.start_md, "well": self.name, "probs": self.probs,
                "planned_td_md": self.tr.td_md}

    # ------------------------------------------------------------------ processing
    def _hist_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.history[-HIST_ROWS:])

    def process_sample(self, s: dict) -> list[dict]:
        s = dict(s)
        s["tvd"] = float(self.tr.tvd_at_md(s["md"]))
        s.setdefault("inc", 0.0)
        s["flow_diff_pct"] = (s["flow_out"] - s["flow_in"]) / max(s["flow_in"], 1.0) * 100.0
        s["mse"] = float(teale_mse_mpa(s["wob"], s["rpm"], s["torque"], s["rop"], self.tr.hole_diameter_at_md(s["md"])))
        self.history.append(s)
        new_alerts: list[dict] = []
        h = self._hist_df()
        if len(h) >= 4:
            s["signals"] = self._signals(h)
            new_alerts += self._realtime_alerts(s, s["signals"])
        new_alerts += self._model_alerts(s, h)
        new_alerts += self._lookahead_alerts(s)
        new_alerts += self._formation_alerts(s)
        for a in new_alerts:
            self._store_alert(a)
        return new_alerts

    @staticmethod
    def _signals(h: pd.DataFrame) -> dict:
        def ratio(col, w=9):
            base = h[col].iloc[:-1].tail(w).median()
            return float(h[col].iloc[-1] / base) if base else 1.0
        def delta(col, w=9):
            return float(h[col].iloc[-1] - h[col].iloc[:-1].tail(w).median())
        return {
            "torque_ratio": ratio("torque"), "rop_ratio": ratio("rop"), "gas_delta": delta("gas"),
            "overpull_delta": delta("overpull"), "flow_diff_pct": float(h["flow_diff_pct"].iloc[-1]),
            "pit_d3": float(h["pit_delta"].iloc[-1] - h["pit_delta"].iloc[-4]), "mse_ratio": ratio("mse"),
        }

    def _fm_at(self, md: float) -> str | None:
        tvd = float(self.tr.tvd_at_md(md))
        cur = None
        for t in self.pred_tops:
            if tvd >= t["tvd"]:
                cur = t["formation"]
        return cur

    def _cooldown(self, key: str, md: float, gap: float = 40.0) -> bool:
        last = self._last_rt.get(key)
        if last is not None and md - last < gap:
            return False
        self._last_rt[key] = md
        return True

    def _mk(self, s, kind, level, hazard, title, message, recommendation="", evidence=None, ahead=None) -> dict:
        return {"well": self.name, "md": round(s["md"], 1), "elapsed_h": s.get("elapsed_h"), "kind": kind, "level": level,
                "hazard": hazard, "title": title, "message": message, "recommendation": recommendation,
                "evidence": evidence or {}, "ahead_m": ahead, "formation": self._fm_at(s["md"]), "feedback": None}

    def set_feedback(self, alert_id: int, status: str) -> dict | None:
        a = next((a for a in self.alerts if a.get("id") == alert_id), None)
        if a is None:
            return None
        a["feedback"] = status
        self.conn.execute("UPDATE alerts SET feedback=? WHERE id=?", (status, alert_id))
        self.conn.commit()
        return a

    def feedback_stats(self) -> dict:
        confirmed = sum(1 for a in self.alerts if a.get("feedback") == "confirmed")
        dismissed = sum(1 for a in self.alerts if a.get("feedback") == "dismissed")
        rated = confirmed + dismissed
        return {"confirmed": confirmed, "dismissed": dismissed, "rated": rated, "total": len(self.alerts),
                "agreement": confirmed / rated if rated else None}

    def _realtime_alerts(self, s: dict, g: dict) -> list[dict]:
        out: list[dict] = []
        md = s["md"]
        if g["flow_diff_pct"] > 2.0 and self._cooldown("kick", md):
            out.append(self._mk(s, "realtime", "critical", "kick", "Possible influx (kick indication)",
                                f"Flow-out exceeds flow-in by {g['flow_diff_pct']:.1f}% (pit change {g['pit_d3']:+.2f} m3 over 15 m).",
                                "Flow-check the well; be ready to shut in. Compare with offset kick responses.", g))
        if g["flow_diff_pct"] < -2.0 and self._cooldown("mud_loss", md):
            loss = -g["flow_diff_pct"] / 100 * s["flow_in"] * 60 / 1000
            out.append(self._mk(s, "realtime", "warning", "mud_loss", "Mud losses detected",
                                f"Flow-out {abs(g['flow_diff_pct']):.1f}% below flow-in (about {loss:.0f} m3/hr).",
                                "Reduce pump rate and prepare an LCM pill.", g))
        if g["torque_ratio"] > 1.25 and g["overpull_delta"] > 1.5 and self._cooldown("stuck_pipe", md):
            out.append(self._mk(s, "realtime", "critical", "stuck_pipe", "Stuck-pipe precursor",
                                f"Torque {g['torque_ratio']:.2f}x its recent trend with overpull +{g['overpull_delta']:.1f} t "
                                f"(mechanical specific energy {s['mse']:.0f} MPa, {g['mse_ratio']:.2f}x trend — a lot of effort for little progress).",
                                "Stop drilling ahead, circulate and work the string; consider a wiper trip.", g))
        elif g["torque_ratio"] > 1.45 and self._cooldown("torque_spike", md):
            out.append(self._mk(s, "realtime", "warning", "torque_spike", "Torque spike",
                                f"Torque {s['torque']:.1f} kNm is {g['torque_ratio']:.2f}x the recent trend "
                                f"(mechanical specific energy {s['mse']:.0f} MPa, {g['mse_ratio']:.2f}x trend).",
                                "Reduce RPM, circulate hole clean.", g))
        if g["rop_ratio"] > 1.5 and g["gas_delta"] > 60 and self._cooldown("overpressure", md):
            out.append(self._mk(s, "realtime", "warning", "overpressure", "Drilling break with rising gas",
                                f"ROP {g['rop_ratio']:.1f}x trend with gas +{g['gas_delta']:.0f} units - possible overpressure.",
                                "Flow-check, review d-exponent trend and consider raising MW.", g))
        return out

    def _model_alerts(self, s: dict, h: pd.DataFrame) -> list[dict]:
        if self.model is None or len(h) < 4:
            return []
        X = build_feature_frame(self.ctx, h.tail(16))
        probs = self.model.predict(X.tail(1))
        self.probs = {k: float(v[0]) for k, v in probs.items()}
        s["probs"] = self.probs
        out = []
        for et, p in self.probs.items():
            thr = self.model.thresholds[et]
            if p < thr * 0.6:
                self._model_armed[et] = True
            last = self._last_model_alert.get(et, -1e9)
            if p >= thr and self._model_armed[et] and s["md"] - last > MODEL_REARM_M / 2:
                self._model_armed[et] = False
                self._last_model_alert[et] = s["md"]
                lvl = "critical" if p >= max(0.5, thr * 2.5) else "warning"
                zone = next((z for z in self.zones if z.type == et and z.md_from - 60 <= s["md"] <= z.md_to + 60), None)
                evidence = {"probability": round(p, 3), "threshold": thr}
                extra = ""
                if zone:
                    evidence["wells"] = zone.wells[:5]
                    evidence["zone_prevalence"] = zone.prevalence
                    extra = f" {len(zone.wells)} offset well(s) ({', '.join(zone.wells[:3])}{'...' if len(zone.wells) > 3 else ''}) had this problem at the equivalent depth."
                out.append(self._mk(
                    s, "model", lvl, et, f"{EVENT_LABELS[et]} risk elevated ({p:.0%})",
                    f"Model estimates a {p:.0%} chance of {EVENT_LABELS[et].lower()} within the next 50 m "
                    f"(alert threshold {thr:.0%}).{extra}", "Review offset lessons for this interval.", evidence))
        return out

    def _lookahead_alerts(self, s: dict) -> list[dict]:
        out = []
        md = s["md"]
        for z in self.zones:
            ahead = z.md_from - md
            inside = z.md_from <= md <= z.md_to
            if z.id in self._zone_alerted or z.level == "low":
                continue
            if -1 < ahead <= ALERT_LOOKAHEAD_M or inside:
                self._zone_alerted.add(z.id)
                lvl = "critical" if z.level == "high" else "warning"
                wells = ", ".join(z.wells[:4]) + ("..." if len(z.wells) > 4 else "")
                out.append(self._mk(
                    s, "lookahead", lvl, z.type,
                    f"{EVENT_LABELS[z.type]} zone {max(ahead, 0):.0f} m ahead ({z.formation})",
                    f"{z.n_wells} offset wells ({wells}) reported {EVENT_LABELS[z.type].lower()} at the equivalent depth "
                    f"{z.md_from:,.0f}-{z.md_to:,.0f} m MD (weighted prevalence {z.prevalence:.0%}"
                    + (f", mean NPT {z.mean_npt_h:.0f} h" if z.mean_npt_h is not None else "") + ").",
                    z.recommendation, {"zone": z.to_dict()}, max(ahead, 0.0)))
        return out

    def _formation_alerts(self, s: dict) -> list[dict]:
        out = []
        md = s["md"]
        for row in self.profile:
            fm = row["formation"]
            ahead = row["top_md"] - md
            if fm in self._fm_alerted or not (-1 < ahead <= FORMATION_ALERT_AHEAD_M):
                continue
            self._fm_alerted.add(fm)
            hz = sorted(((et, r["prevalence"]) for et, r in row["risk"].items() if r["events"] and et != "fishing"), key=lambda kv: -kv[1])[:3]
            if row["expected_npt_h"] < 3 or not hz:
                continue
            txt = ", ".join(f"{EVENT_LABELS[et].lower()} {p:.0%}" for et, p in hz)
            out.append(self._mk(
                s, "formation", "warning" if row["expected_npt_h"] < 12 else "critical", hz[0][0],
                f"Entering {fm} in ~{max(ahead, 0):.0f} m", f"Predicted top {row['top_md']:,.0f} m MD (+/-{row['sigma_m']:.0f} m). "
                f"Historical hazards in {row['n_offsets']} offsets: {txt}. Expected NPT {row['expected_npt_h']:.0f} h.",
                "Review the formation lessons and pre-stage contingency materials.", {"formation": row}, max(ahead, 0.0)))
        return out

    def _store_alert(self, a: dict) -> None:
        cur = self.conn.execute(
            "INSERT INTO alerts(well_id,level,kind,md,title,message,payload) VALUES(?,?,?,?,?,?,?)",
            (self.well_id, a["level"], a["kind"], a["md"], a["title"], a["message"], j(a)))
        a["id"] = cur.lastrowid
        self.conn.commit()
        self.alerts.append(a)

    # ------------------------------------------------------------------ replay control
    def step(self) -> dict | None:
        if self.idx >= len(self.replay):
            self.running = False
            return None
        row = self.replay.iloc[self.idx]
        self.idx += 1
        sample = {c: float(row[c]) for c in ["md", "inc", "elapsed_h", *LIVE_COLS] if c in row.index}
        alerts = self.process_sample(sample)
        enriched = self.history[-1]  # process_sample() enriches a COPY of `sample` (tvd, mse, probs, ...); publish that, not the raw input
        self.publish("sample", enriched)
        for a in alerts:
            self.publish("alert", a)
        return enriched

    async def run(self) -> None:
        while True:
            if self.running:
                if self.step() is None:
                    self.publish("state", self.state())
                    self.running = False
                elif self.idx % 5 == 0:
                    self.publish("state", self.state())
                await asyncio.sleep(max(0.01, 1.0 / max(self.speed, 0.1)))
            else:
                await asyncio.sleep(0.15)

    def ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    def snapshot(self) -> dict:
        hist = [{k: v for k, v in s.items() if k in ("md", "tvd", "elapsed_h", "rop", "wob", "rpm", "torque", "spp", "flow_in", "flow_out",
                                                     "pit_delta", "mw", "gas", "overpull", "flow_diff_pct", "mse", "probs")} for s in self.history]
        return {"state": self.state(), "history": hist, "alerts": self.alerts, "zones": [z.to_dict() for z in self.zones],
                "tops": self.pred_tops}
