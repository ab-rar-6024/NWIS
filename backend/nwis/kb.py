"""In-memory analytical view of the knowledge base: trajectories, formation tops, events, offset selection."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from .geo import hole_diameter_in, latlon_to_km

TVD_GRID_STEP = 250.0


@dataclass
class Trajectory:
    id: int
    name: str
    field: str | None
    status: str | None
    east0: float  # surface position, km
    north0: float
    md: np.ndarray
    tvd: np.ndarray
    e_m: np.ndarray  # offsets from wellhead in metres
    n_m: np.ndarray
    td_md: float
    td_tvd: float
    tops: list[dict] = field(default_factory=list)  # [{formation, md, tvd}] sorted by tvd
    casing: list[dict] = field(default_factory=list)  # [{hole_in, shoe_md}] sorted by shoe_md; the current (open) hole below the last shoe extends to TD
    has_survey: bool = False
    lat: float | None = None
    lon: float | None = None

    def pos_at_tvd(self, tvd_q: float) -> tuple[float, float]:
        t = float(np.clip(tvd_q, self.tvd[0], self.tvd[-1]))
        return (self.east0 + float(np.interp(t, self.tvd, self.e_m)) / 1000.0,
                self.north0 + float(np.interp(t, self.tvd, self.n_m)) / 1000.0)

    def pos_at_md(self, md_q: float) -> tuple[float, float]:
        m = float(np.clip(md_q, self.md[0], self.md[-1]))
        return (self.east0 + float(np.interp(m, self.md, self.e_m)) / 1000.0,
                self.north0 + float(np.interp(m, self.md, self.n_m)) / 1000.0)

    def tvd_at_md(self, md_q):
        return np.interp(md_q, self.md, self.tvd)

    def md_at_tvd(self, tvd_q):
        return np.interp(tvd_q, self.tvd, self.md)

    def formation_at_tvd(self, tvd_q: float) -> str | None:
        fm = None
        for t in self.tops:
            if tvd_q >= t["tvd"]:
                fm = t["formation"]
            else:
                break
        return fm

    def top_tvd(self, formation: str) -> float | None:
        for t in self.tops:
            if t["formation"] == formation:
                return t["tvd"]
        return None

    def hole_diameter_at_md(self, md_q: float) -> float | None:
        """Bit/hole diameter (inches) currently open at this depth, from the well's casing programme."""
        if not self.casing:
            return None
        for c in self.casing:
            if md_q <= c["shoe_md"]:
                return c["hole_in"]
        return self.casing[-1]["hole_in"]  # drilling ahead in open hole past the last set shoe

    def hole_diameter_at_md_arr(self, md_q: np.ndarray) -> np.ndarray:
        if not self.casing:
            return np.full(len(md_q), np.nan)
        shoes = np.array([c["shoe_md"] for c in self.casing])
        holes = np.array([c["hole_in"] for c in self.casing])
        idx = np.clip(np.searchsorted(shoes, md_q, side="left"), 0, len(holes) - 1)
        return holes[idx]


def separation_km(a: Trajectory, b: Trajectory, tvd_q: float) -> float:
    ea, na = a.pos_at_tvd(tvd_q)
    eb, nb = b.pos_at_tvd(tvd_q)
    return float(np.hypot(ea - eb, na - nb))


def closest_approach_km(a: Trajectory, b: Trajectory) -> float:
    """Minimum horizontal separation over the TVD interval both wells cover (incl. surface)."""
    top = min(a.tvd[-1], b.tvd[-1])
    grid = np.arange(0.0, top + 1, TVD_GRID_STEP)
    if len(grid) == 0:
        grid = np.array([0.0])
    return float(min(separation_km(a, b, t) for t in grid))


class KnowledgeIndex:
    """Loads everything the analytics need in one pass; call reload() after ingestion."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.reload()

    def reload(self) -> None:
        c = self.conn
        self.traj: dict[int, Trajectory] = {}
        surveys: dict[int, list] = {}
        for r in c.execute("SELECT well_id, md, tvd, north, east FROM surveys ORDER BY well_id, md"):
            surveys.setdefault(r["well_id"], []).append((r["md"], r["tvd"], r["north"], r["east"]))
        tops: dict[int, list] = {}
        for r in c.execute("SELECT well_id, formation, md, tvd FROM formation_tops ORDER BY well_id, tvd"):
            tops.setdefault(r["well_id"], []).append({"formation": r["formation"], "md": r["md"], "tvd": r["tvd"]})
        casing: dict[int, list] = {}
        for r in c.execute("SELECT well_id, hole, shoe_md FROM casing ORDER BY well_id, shoe_md"):
            d = hole_diameter_in(r["hole"])
            if d is not None:
                casing.setdefault(r["well_id"], []).append({"hole_in": d, "shoe_md": r["shoe_md"]})
        self.wells: dict[int, dict] = {}
        for w in c.execute("SELECT * FROM wells"):
            w = dict(w)
            self.wells[w["id"]] = w
            if w["lat"] is None or w["lon"] is None:
                continue
            e0, n0 = latlon_to_km(w["lat"], w["lon"])
            sv = surveys.get(w["id"])
            if sv:
                arr = np.array(sv)
                md, tvd, north, east = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
                has = True
            else:  # documents only (no survey): assume vertical
                td = w.get("td_md") or w.get("planned_td_md") or 4000.0
                md = np.array([0.0, td])
                tvd = md.copy()
                north = np.zeros(2)
                east = np.zeros(2)
                has = False
            # guard against non-monotonic TVD (needed for interpolation)
            tvd = np.maximum.accumulate(tvd)
            tvd = tvd + np.arange(len(tvd)) * 1e-6
            self.traj[w["id"]] = Trajectory(
                id=w["id"], name=w["name"], field=w["field"], status=w["status"], east0=e0, north0=n0, md=md, tvd=tvd,
                e_m=east, n_m=north, td_md=float(md[-1]), td_tvd=float(tvd[-1]), tops=tops.get(w["id"], []),
                casing=casing.get(w["id"], []), has_survey=has, lat=w["lat"], lon=w["lon"],
            )
        # regional reference tops (mean TVD per formation) -> common stratigraphic depth axis
        acc: dict[str, list[float]] = {}
        for t in self.traj.values():
            for tp in t.tops:
                acc.setdefault(tp["formation"], []).append(tp["tvd"])
        self.ref_tops = {f: float(np.mean(v)) for f, v in acc.items()}
        self.formation_order = [f for f, _ in sorted(self.ref_tops.items(), key=lambda kv: kv[1])]

        self.events: list[dict] = []
        for r in c.execute("SELECT * FROM events"):
            e = dict(r)
            e["mitigations"] = json.loads(e["mitigations"] or "[]")
            e["details"] = json.loads(e["details"] or "{}")
            e["sources"] = json.loads(e["sources"] or "[]")
            w = self.traj.get(e["well_id"])
            e["z"] = self.zdepth(e["tvd"], w.tops) if (w and e["tvd"] is not None) else None
            self.events.append(e)
        self.events_by_well: dict[int, list[dict]] = {}
        for e in self.events:
            self.events_by_well.setdefault(e["well_id"], []).append(e)

    # ------------------------------------------------------------------ coordinates
    def zdepth(self, tvd: float, tops: list[dict]):
        """Map a well's TVD onto the regional stratigraphic depth axis (formation-relative)."""
        if not tops or tvd is None:
            return tvd
        fm = None
        for t in tops:
            if tvd >= t["tvd"]:
                fm = t
            else:
                break
        if fm is None:
            return tvd
        ref = self.ref_tops.get(fm["formation"])
        return tvd if ref is None else ref + (tvd - fm["tvd"])

    # ------------------------------------------------------------------ offsets
    def nearby(self, target: Trajectory, radius_km: float, exclude_active: bool = True, max_n: int | None = None) -> list[tuple[Trajectory, float]]:
        out = []
        for t in self.traj.values():
            if t.id == target.id:
                continue
            if exclude_active and (t.status or "").upper() == "ACTIVE":
                continue
            d = closest_approach_km(target, t)
            if d <= radius_km:
                out.append((t, d))
        out.sort(key=lambda x: x[1])
        return out[:max_n] if max_n else out
