"""Synthetic well generator: trajectory, tops, casing, mud, hazard events and drilling logs."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import AREA_LAT0, AREA_LON0
from ..geo import km_to_latlon, min_curvature
from . import geology as G

LOG_STEP = 5.0  # m between drilling-log samples
SURVEY_STEP = 30.0

ROP_BASE = {
    "Alluvium": 45, "Namsang": 38, "Girujan Clay": 30, "Tipam Sandstone": 24,
    "Barail Coal Shale": 14, "Barail Sandstone": 12, "Kopili Shale": 9,
    "Sylhet Limestone": 6, "Langpar-Lakadong": 6, "Therria": 5,
}

RIGS = ["IDECO-2000", "NATIONAL-1320", "BHEL-3000", "OIL-750-M", "IRI-2000"]


@dataclass
class Event:
    id: str
    type: str
    md: float
    tvd: float
    formation: str
    npt_h: float
    details: dict = field(default_factory=dict)


@dataclass
class Well:
    name: str
    field: str
    e_km: float
    n_km: float
    lat: float
    lon: float
    year: int
    spud_date: date
    status: str
    rig: str
    kb_m: float
    td_md: float
    td_tvd: float
    survey: pd.DataFrame
    tops_tvd: dict
    tops_md: dict
    casing: list
    mud: list
    events: list
    logs: pd.DataFrame
    directional: bool


def _smooth_noise(rng: np.random.Generator, n: int, corr: float = 0.85, sd: float = 1.0) -> np.ndarray:
    x = np.zeros(n)
    e = rng.normal(0, sd, n)
    for i in range(1, n):
        x[i] = corr * x[i - 1] + math.sqrt(1 - corr**2) * e[i]
    return x


def _build_trajectory(rng, td_tvd_target: float, directional: bool):
    """Return survey DataFrame (30 m stations) reaching approximately the target TVD."""
    max_md = td_tvd_target * (1.25 if directional else 1.02) + 200
    mds = np.arange(0.0, max_md + SURVEY_STEP, SURVEY_STEP)
    inc = np.zeros_like(mds)
    azi = np.zeros_like(mds)
    a0 = rng.uniform(0, 360)
    if directional:
        kop = rng.uniform(400, 900)
        target_inc = rng.uniform(14, 34)
        build = rng.uniform(1.2, 2.4)  # deg per station
        cur = 0.0
        for i, md in enumerate(mds):
            if md > kop and cur < target_inc:
                cur = min(target_inc, cur + build)
            elif md > kop + 1500 and rng.random() < 0.5:
                cur = max(4.0, cur - 0.4)  # gentle drop-off
            inc[i] = cur + rng.normal(0, 0.25)
        azi[:] = a0 + np.cumsum(rng.normal(0, 0.6, len(mds)))
    else:
        inc = np.clip(0.6 + 0.9 * np.abs(_smooth_noise(rng, len(mds), 0.9, 1.0)), 0, 4.5)
        azi[:] = a0 + np.cumsum(rng.normal(0, 4.0, len(mds)))
    inc = np.clip(inc, 0, 60)
    azi = np.mod(azi, 360)
    tvd, north, east = min_curvature(mds, inc, azi)
    df = pd.DataFrame({"md": mds, "inc": inc, "azi": azi, "tvd": tvd, "north": north, "east": east})
    return df


def _md_at_tvd(survey: pd.DataFrame, tvd_q: float) -> float:
    return float(np.interp(tvd_q, survey["tvd"].values, survey["md"].values))


def _tvd_at_md(survey: pd.DataFrame, md_q):
    return np.interp(md_q, survey["md"].values, survey["tvd"].values)


def _design_casing(tops_tvd, tops_md, td_md, td_tvd, survey, rng):
    kop_shoe = tops_tvd["Kopili Shale"]
    surface_md = _md_at_tvd(survey, tops_tvd["Girujan Clay"] + rng.uniform(40, 90))
    casing = [
        {"size": '20"', "hole": '26"', "shoe_md": 60.0, "grade": "K-55", "planned_toc_md": 0.0},
        {"size": '13-3/8"', "hole": '17-1/2"', "shoe_md": round(surface_md, 0), "grade": "K-55", "planned_toc_md": 0.0},
    ]
    if td_tvd >= kop_shoe + 150:
        inter_md = _md_at_tvd(survey, kop_shoe - rng.uniform(40, 80))
        casing.append({"size": '9-5/8"', "hole": '12-1/4"', "shoe_md": round(inter_md, 0), "grade": "N-80",
                       "planned_toc_md": round(surface_md - 150, 0)})
        casing.append({"size": '7"', "hole": '8-1/2"', "shoe_md": round(td_md, 0), "grade": "P-110",
                       "planned_toc_md": round(inter_md - 200, 0)})
    else:
        casing.append({"size": '9-5/8"', "hole": '12-1/4"', "shoe_md": round(td_md, 0), "grade": "N-80",
                       "planned_toc_md": round(surface_md - 150, 0)})
    for c in casing:
        c["toc_md"] = c["planned_toc_md"]  # achieved TOC; may be degraded by cementing events
    return casing


def _hole_at(md: float, casing: list) -> str:
    for c in casing:
        if md <= c["shoe_md"]:
            return c["hole"]
    return casing[-1]["hole"]


def _sample_events(rng, name, e_km, n_km, survey, tops_tvd, td_md, casing):
    """Sample hazard events per 10 m MD bin."""
    events: list[Event] = []
    last_by_type: dict[str, float] = {}
    counter = 0
    start_md = casing[1]["shoe_md"] if len(casing) > 1 else 60.0
    # shallow hazards below the conductor are allowed; start just under conductor
    for md in np.arange(70.0, td_md, 10.0):
        tvd = float(_tvd_at_md(survey, md + 5))
        fm = G.formation_at_tvd(tvd, tops_tvd)
        east = e_km + float(np.interp(md, survey["md"], survey["east"])) / 1000.0
        north = n_km + float(np.interp(md, survey["md"], survey["north"])) / 1000.0
        for et, base in G.BASE_RATE.get(fm, {}).items():
            lam = base * G.hazard_multiplier(et, fm, east, north) * (10.0 / 100.0)
            if rng.random() < 1 - math.exp(-lam):
                if md - last_by_type.get(et, -1e9) < 25:
                    continue
                last_by_type[et] = md
                counter += 1
                ev_md = float(md + rng.uniform(0, 10))
                events.append(Event(f"{name}-E{counter:02d}", et, ev_md, float(_tvd_at_md(survey, ev_md)), fm, 0.0))
    return events


def _fill_event_details(ev: Event, rng, casing, mw_at):
    d: dict = {}
    if ev.type == "mud_loss":
        rate = float(np.clip(rng.lognormal(math.log(8), 0.9), 0.8, 90))
        d["rate_m3h"] = round(rate, 1)
        d["severity"] = "seepage" if rate < 3 else ("partial" if rate < 20 else ("severe" if rate < 45 else "total"))
        d["lcm_type"] = str(rng.choice(["fine nut plug", "medium mica/CaCO3", "coarse fibre", "sized CaCO3", "graphite blend"]))
        d["lcm_vol_m3"] = int(rng.integers(8, 35))
        d["lcm_ppb"] = int(rng.integers(20, 55))
        if d["severity"] in ("severe", "total") and rng.random() < 0.45:
            d["mitigation"] = "cement_plug"
            d["outcome"] = "cured" if rng.random() < 0.7 else "blind"
        elif d["severity"] == "seepage":
            d["mitigation"] = "reduce_rate"
            d["outcome"] = "cured"
        else:
            d["mitigation"] = "lcm_pill"
            d["outcome"] = "cured" if rng.random() < 0.65 else "reduced"
        d["residual_m3h"] = round(rate * rng.uniform(0.08, 0.3), 1)
        ev.npt_h = round(float(np.clip(rate * rng.uniform(0.15, 0.6), 1, 40)), 1)
    elif ev.type == "kick":
        d["gain_m3"] = round(float(np.clip(rng.lognormal(math.log(2.0), 0.7), 0.4, 12)), 1)
        d["sidpp_bar"] = int(rng.integers(5, 42))
        d["sicp_bar"] = d["sidpp_bar"] + int(rng.integers(2, 16))
        mw0 = mw_at(ev.md)
        d["mw0"] = round(mw0, 2)
        d["mw1"] = round(min(mw0 + rng.uniform(0.04, 0.15), 1.80), 2)
        d["mw1"] = max(d["mw1"], d["mw0"])
        d["method"] = str(rng.choice(["Driller's method", "Wait and Weight method"]))
        d["mitigation"] = "weight_up"
        d["outcome"] = "controlled"
        ev.npt_h = round(float(rng.uniform(8, 36)), 1)
    elif ev.type == "stuck_pipe":
        if ev.formation == "Kopili Shale":
            mech = str(rng.choice(["hole collapse", "pack-off"], p=[0.6, 0.4]))
        elif ev.formation == "Barail Coal Shale":
            mech = str(rng.choice(["pack-off", "mechanical (key-seat)"], p=[0.7, 0.3]))
        else:
            mech = str(rng.choice(["differential sticking", "pack-off", "mechanical (key-seat)"], p=[0.4, 0.35, 0.25]))
        d["mechanism"] = mech
        d["overpull_t"] = int(rng.integers(15, 65))
        r = rng.random()
        if r < 0.45:
            d["mitigation"], ev.npt_h = "jarring", round(float(rng.uniform(4, 24)), 1)
        elif r < 0.75:
            d["mitigation"], ev.npt_h = "freeing_pill", round(float(rng.uniform(12, 48)), 1)
        else:
            d["mitigation"], ev.npt_h = "backoff", round(float(rng.uniform(48, 120)), 1)
        d["outcome"] = "freed" if d["mitigation"] != "backoff" else "fish_left"
        d["op"] = str(rng.choice(["pulling out of hole", "making a connection", "reaming", "running in hole", "drilling ahead"]))
    elif ev.type == "overpressure":
        d["gas_units"] = int(rng.integers(150, 950))
        mw0 = mw_at(ev.md)
        d["mw0"] = round(mw0, 2)
        d["mw1"] = round(min(mw0 + rng.uniform(0.04, 0.14), 1.80), 2)
        d["mw1"] = max(d["mw1"], d["mw0"])
        d["pp_sg"] = round(d["mw1"] - rng.uniform(0.01, 0.04), 2)
        d["mitigation"] = "weight_up"
        d["outcome"] = "controlled"
        ev.npt_h = round(float(rng.uniform(2, 14)), 1)
    elif ev.type == "torque_spike":
        d["baseline_knm"] = round(float(rng.uniform(9, 16)), 1)
        d["peak_knm"] = round(d["baseline_knm"] * rng.uniform(1.7, 2.8), 1)
        d["mitigation"] = "reduce_rpm"
        d["outcome"] = "normalised"
        ev.npt_h = round(float(rng.uniform(0.5, 8)), 1)
    elif ev.type == "cementing_issue":
        d["kind"] = str(rng.choice(["poor bond", "low top of cement", "channeling"]))
        d["squeeze_vol_m3"] = int(rng.integers(6, 30))
        d["mitigation"] = "squeeze"
        d["outcome"] = "remediated"
        ev.npt_h = round(float(rng.uniform(8, 40)), 1)
    elif ev.type == "fishing":
        d["tool"] = str(rng.choice(["stabilizer", "drill collar", "roller-cone bit cones", "MWD tool", "BHA section"]))
        d["recovered"] = bool(rng.random() < 0.78)
        d["mitigation"] = "fishing_run"
        d["outcome"] = "recovered" if d["recovered"] else "abandoned_fish"
        ev.npt_h = round(float(rng.uniform(12, 96)), 1)
    ev.details = d


def _planned_mw(md: float, tvd: float) -> float:
    return 1.05 + 0.00008 * tvd


def _build_logs(rng, survey, tops_tvd, td_md, casing, events, e_km, n_km):
    mds = np.arange(LOG_STEP, td_md + 1e-6, LOG_STEP)
    n = len(mds)
    tvd = np.interp(mds, survey["md"], survey["tvd"])
    inc = np.interp(mds, survey["md"], survey["inc"])
    fms = [G.formation_at_tvd(t, tops_tvd) for t in tvd]
    rop_base = np.array([ROP_BASE[f] for f in fms], float)
    rop = rop_base * np.exp(0.25 * _smooth_noise(rng, n, 0.9))
    wob = np.clip(8 + 0.0015 * mds + 1.2 * _smooth_noise(rng, n, 0.9), 3, 20)
    rpm = np.clip(105 + 20 * np.sin(mds / 900.0) + 6 * _smooth_noise(rng, n, 0.9), 60, 150)
    torque = np.clip(5.0 + 0.0035 * mds + 0.09 * inc + 0.8 * _smooth_noise(rng, n, 0.9), 2, 40)
    spp = np.clip(110 + 0.035 * mds + 4 * _smooth_noise(rng, n, 0.9), 60, 300)
    flow_in = np.clip(3300 - 0.22 * mds, 1800, 3400).astype(float) + 20 * _smooth_noise(rng, n, 0.8)
    flow_out = flow_in * (1 + 0.004 * _smooth_noise(rng, n, 0.6))
    pit = 0.08 * _smooth_noise(rng, n, 0.5)
    gas = np.clip(30 + 12 * _smooth_noise(rng, n, 0.9), 5, 120)
    overpull = np.clip(3.5 + 0.8 * _smooth_noise(rng, n, 0.9), 0.5, 10)
    mw = np.array([_planned_mw(m, t) for m, t in zip(mds, tvd)])

    def idx(md_q):
        return int(np.clip(round((md_q - LOG_STEP) / LOG_STEP), 0, n - 1))

    for ev in events:
        i = idx(ev.md)
        pre = lambda k: slice(max(0, i - k), i + 1)
        if ev.type == "stuck_pipe":
            k = 7
            ramp = np.linspace(0.1, 1.0, len(range(*pre(k).indices(n))))
            torque[pre(k)] *= 1 + 0.55 * ramp
            overpull[pre(4)] += np.linspace(2, ev.details["overpull_t"] * 0.5, len(range(*pre(4).indices(n))))
            rop[pre(5)] *= np.linspace(0.95, 0.65, len(range(*pre(5).indices(n))))
            spp[pre(3)] += np.linspace(2, 12, len(range(*pre(3).indices(n))))
        elif ev.type == "torque_spike":
            k = 4
            ramp = np.linspace(0.15, 1.0, len(range(*pre(k).indices(n))))
            base = torque[i]
            torque[pre(k)] = base + (ev.details["peak_knm"] - base) * ramp
        elif ev.type == "mud_loss":
            rate_lpm = ev.details["rate_m3h"] * 1000 / 60
            hi = slice(i, min(n, i + 4))
            flow_out[hi] -= rate_lpm
            pit[i:] -= np.minimum(ev.details["rate_m3h"] * 0.05, 3.0) * 0.5
            spp[hi] *= 0.92
            rop[pre(3)] *= np.linspace(1.0, 1.5, len(range(*pre(3).indices(n))))
        elif ev.type in ("kick", "overpressure"):
            k = 7
            m = len(range(*pre(k).indices(n)))
            ramp = np.linspace(0.1, 1.0, m)
            rop[pre(k)] *= 1 + 0.9 * ramp
            gas_pk = ev.details.get("gas_units", 400)
            gas[pre(k)] += gas_pk * 0.6 * ramp
            if ev.type == "kick":
                hi = slice(i, min(n, i + 3))
                flow_out[hi] += flow_in[hi] * 0.05 * (ev.details["gain_m3"] / 3 + 0.5)
                pit[i:] += ev.details["gain_m3"] * 0.3
            mw[i + 1:] = np.maximum(mw[i + 1:], ev.details["mw1"])
    return pd.DataFrame({
        "md": mds, "tvd": tvd, "inc": inc, "formation": fms, "rop": rop, "wob": wob, "rpm": rpm,
        "torque": torque, "spp": spp, "flow_in": flow_in, "flow_out": flow_out, "pit_delta": pit,
        "mw": mw, "gas": gas, "overpull": overpull,
    })


def generate_well(
    name: str,
    field_name: str,
    e_km: float,
    n_km: float,
    rng: np.random.Generator,
    year: int,
    status: str = "COMPLETED",
    forced: list[tuple[str, str, float]] | None = None,
    force_deep: bool = False,
) -> Well:
    tops_tvd = G.formation_tops_tvd(e_km, n_km, rng)
    directional = bool(rng.random() < 0.38)
    r = rng.random()
    if force_deep or r < 0.62:
        td_tvd = float(rng.uniform(3600, 3950))
    elif r < 0.82:
        td_tvd = float(rng.uniform(3300, 3550))
    else:
        td_tvd = float(rng.uniform(2650, 3150))
    if force_deep:
        td_tvd = 3900.0 if directional is False else 3850.0
    survey = _build_trajectory(rng, td_tvd, directional)
    td_md = _md_at_tvd(survey, td_tvd)
    td_md = round(td_md / 5) * 5.0
    survey = survey[survey["md"] <= td_md + SURVEY_STEP].reset_index(drop=True)
    tops_md = {f: round(_md_at_tvd(survey, t), 1) for f, t in tops_tvd.items() if t < td_tvd}
    casing = _design_casing(tops_tvd, tops_md, td_md, td_tvd, survey, rng)

    events = _sample_events(rng, name, e_km, n_km, survey, tops_tvd, td_md, casing)

    # forced scenario events for the live demo well (formation, type, offset below top in TVD)
    if forced:
        for k, (fm, et, off) in enumerate(forced):
            tvd_f = tops_tvd[fm] + off
            md_f = _md_at_tvd(survey, tvd_f)
            events = [e for e in events if not (e.type == et and abs(e.md - md_f) < 60)]
            events.append(Event(f"{name}-F{k:02d}", et, float(md_f), float(tvd_f), fm, 0.0))

    # fishing follows some back-off stuck pipe events
    tmp: list[Event] = []
    for ev in sorted(events, key=lambda x: x.md):
        tmp.append(ev)
    events = tmp

    mw_floor = [0.0]  # running weight-up floor so consecutive events stay consistent

    def mw_at(md_q: float) -> float:
        return max(_planned_mw(md_q, float(_tvd_at_md(survey, md_q))), mw_floor[0])

    for ev in events:
        _fill_event_details(ev, rng, casing, mw_at)
        if "mw1" in ev.details:
            mw_floor[0] = max(mw_floor[0], ev.details["mw1"])
    extra = []
    for ev in events:
        if ev.type == "stuck_pipe" and ev.details["mitigation"] == "backoff":
            fe = Event(ev.id + "-FISH", "fishing", ev.md + float(rng.uniform(0, 4)), ev.tvd, ev.formation, 0.0)
            _fill_event_details(fe, rng, casing, mw_at)
            extra.append(fe)
    events += extra

    # cementing issues at casing points
    for c in casing[1:]:
        shoe_fm = G.formation_at_tvd(float(_tvd_at_md(survey, c["shoe_md"])), tops_tvd)
        p = 0.12 + (0.22 if shoe_fm in ("Barail Coal Shale", "Kopili Shale", "Barail Sandstone") else 0.0)
        if rng.random() < p:
            ce = Event(f"{name}-C{len(events):02d}", "cementing_issue", c["shoe_md"],
                       float(_tvd_at_md(survey, c["shoe_md"])), shoe_fm, 0.0)
            _fill_event_details(ce, rng, casing, mw_at)
            ce.details["casing"] = c["size"]
            if ce.details["kind"] == "low top of cement":
                c["toc_md"] = round(c["planned_toc_md"] + float(rng.uniform(150, 450)), 0)
            events.append(ce)

    events = sorted(events, key=lambda x: (x.md, x.type))
    for i, ev in enumerate(events, 1):
        ev.id = f"{name}-EV{i:02d}"

    logs = _build_logs(rng, survey, tops_tvd, td_md, casing, [e for e in events if e.type not in ("cementing_issue", "fishing")], e_km, n_km)

    mud = []
    for i, c in enumerate(casing):
        top = 0.0 if i == 0 else casing[i - 1]["shoe_md"]
        fm_lo = float(_tvd_at_md(survey, top))
        fm_hi = float(_tvd_at_md(survey, c["shoe_md"]))
        mtype = "Spud mud (bentonite-water)" if i <= 1 else ("KCl-polymer WBM" if i == 2 else "Low-solids polymer WBM")
        seg = logs[(logs["md"] > top) & (logs["md"] <= c["shoe_md"])]
        mw_min = float(seg["mw"].min()) if len(seg) else _planned_mw(top, fm_lo)
        mw_max = float(seg["mw"].max()) if len(seg) else _planned_mw(c["shoe_md"], fm_hi)
        mud.append({"hole": c["hole"], "from_md": top, "to_md": c["shoe_md"], "mud_type": mtype,
                    "mw_min": round(mw_min, 2), "mw_max": round(mw_max, 2)})

    lat, lon = km_to_latlon(e_km, n_km)
    days_to_drill = int(td_md / 55) + 12
    spud = date(year, int(rng.integers(1, 12)), int(rng.integers(1, 28)))
    return Well(
        name=name, field=field_name, e_km=e_km, n_km=n_km, lat=lat, lon=lon, year=year, spud_date=spud,
        status=status, rig=str(rng.choice(RIGS)), kb_m=round(float(rng.uniform(96, 128)), 1), td_md=td_md,
        td_tvd=round(float(_tvd_at_md(survey, td_md)), 1), survey=survey, tops_tvd=tops_tvd, tops_md=tops_md,
        casing=casing, mud=mud, events=events, logs=logs, directional=directional,
    )


def generate_field(seed: int = 26121, wells_per_field: int = 15):
    """Generate all historical wells plus the live 'active' well. Returns (wells, active_well)."""
    master = np.random.default_rng(seed)
    wells: list[Well] = []
    for fname, spec in G.FIELDS.items():
        cx, cy = spec["centre"]
        pts: list[tuple[float, float]] = []
        tries = 0
        while len(pts) < wells_per_field and tries < 500:
            tries += 1
            e = float(master.normal(cx, spec["sigma"]))
            n = float(master.normal(cy, spec["sigma"]))
            if all(math.hypot(e - pe, n - pn) > 0.7 for pe, pn in pts):
                pts.append((e, n))
        years = sorted(int(y) for y in master.integers(2006, 2025, len(pts)))
        for i, ((e, n), y) in enumerate(zip(pts, years), 1):
            rng = np.random.default_rng(master.integers(0, 2**31))
            wells.append(generate_well(f"{spec['code']}-{i:02d}", fname, e, n, rng, y))

    rng = np.random.default_rng(master.integers(0, 2**31))
    forced = [
        ("Tipam Sandstone", "mud_loss", 110),
        ("Barail Coal Shale", "torque_spike", 70),
        ("Barail Coal Shale", "stuck_pipe", 135),
        ("Kopili Shale", "overpressure", 105),
        ("Kopili Shale", "kick", 135),
        ("Sylhet Limestone", "mud_loss", 55),
    ]
    active = generate_well("MRH-17", "Moranhat", G.ACTIVE_WELL_KM[0], G.ACTIVE_WELL_KM[1], rng, 2026,
                           status="ACTIVE", forced=forced, force_deep=True)
    return wells, active
