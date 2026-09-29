"""Illustrative geology + hazard model for the SYNTHETIC demo field.

Everything here is fictional and only loosely inspired by Upper-Assam-style stratigraphy.
Hazards are spatially clustered (fault-zone losses, an overpressure pocket, a coal-rich
stuck-pipe area) so that nearby wells genuinely carry information about each other,
which is the premise of the NWIS product.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# (name, reference top TVD in metres at the field origin)
FORMATIONS: list[tuple[str, float]] = [
    ("Alluvium", 0.0),
    ("Namsang", 350.0),
    ("Girujan Clay", 900.0),
    ("Tipam Sandstone", 1450.0),
    ("Barail Coal Shale", 2050.0),
    ("Barail Sandstone", 2500.0),
    ("Kopili Shale", 2900.0),
    ("Sylhet Limestone", 3250.0),
    ("Langpar-Lakadong", 3450.0),
    ("Therria", 3700.0),
]
FORMATION_NAMES = [f for f, _ in FORMATIONS]

# events per 100 m drilled, per formation (before spatial multipliers)
BASE_RATE: dict[str, dict[str, float]] = {
    "Alluvium": {"mud_loss": 0.05},
    "Namsang": {"mud_loss": 0.12},
    "Girujan Clay": {"stuck_pipe": 0.06, "torque_spike": 0.05},
    "Tipam Sandstone": {"mud_loss": 0.10, "stuck_pipe": 0.04},
    "Barail Coal Shale": {"stuck_pipe": 0.20, "torque_spike": 0.20, "mud_loss": 0.05},
    "Barail Sandstone": {"mud_loss": 0.08, "stuck_pipe": 0.05},
    "Kopili Shale": {"overpressure": 0.12, "kick": 0.08, "stuck_pipe": 0.10, "torque_spike": 0.12},
    "Sylhet Limestone": {"mud_loss": 0.28, "kick": 0.04},
    "Langpar-Lakadong": {"mud_loss": 0.12, "kick": 0.05, "overpressure": 0.05},
    "Therria": {"mud_loss": 0.10},
}

# Fields (fictional): centre (east_km, north_km) and well scatter
FIELDS = {
    "Digaru": {"code": "DGR", "centre": (-7.0, 4.0), "sigma": 2.6},
    "Moranhat": {"code": "MRH", "centre": (7.0, 6.0), "sigma": 2.6},
    "Barsila": {"code": "BRS", "centre": (0.0, -9.0), "sigma": 2.4},
}

# Location of the demo "active" well drilling live in the replay.
ACTIVE_WELL_KM = (3.0, 5.5)


def _gauss(d2: float, sigma: float) -> float:
    return math.exp(-d2 / (2 * sigma**2))


def _dist_to_line_km(e: float, n: float, p0=(-10.0, -2.0), direction=(1.0, 0.45)) -> float:
    dx, dy = direction
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    px, py = e - p0[0], n - p0[1]
    return abs(px * dy - py * dx)


def hazard_multiplier(event_type: str, formation: str, e_km: float, n_km: float) -> float:
    m = 1.0
    if event_type in ("overpressure", "kick") and formation in ("Kopili Shale", "Langpar-Lakadong"):
        m *= 1 + 3.5 * _gauss((e_km - 5.0) ** 2 + (n_km - 8.0) ** 2, 3.5)
    if event_type == "mud_loss" and formation in ("Sylhet Limestone", "Langpar-Lakadong"):
        m *= 1 + 3.5 * _gauss(_dist_to_line_km(e_km, n_km) ** 2, 1.5)
    if event_type == "mud_loss" and formation == "Tipam Sandstone":
        m *= 1 + 1.0 * _gauss(_dist_to_line_km(e_km, n_km) ** 2, 1.8)
    if event_type in ("stuck_pipe", "torque_spike") and formation == "Barail Coal Shale":
        m *= 1 + 1.2 * _gauss((e_km + 6.0) ** 2 + (n_km - 3.0) ** 2, 4.0)
    return m


def formation_tops_tvd(e_km: float, n_km: float, rng: np.random.Generator) -> dict[str, float]:
    """Structural model: gentle regional dip + smooth undulation + small per-well noise."""
    tops: dict[str, float] = {}
    for i, (name, base) in enumerate(FORMATIONS):
        if i == 0:
            tops[name] = 0.0
            continue
        dip = 7.0 * e_km - 4.0 * n_km
        wave = 18.0 * math.sin(0.55 * e_km + 0.3 * i) + 14.0 * math.cos(0.4 * n_km - 0.2 * i)
        tops[name] = base + dip + wave + float(rng.normal(0, 6.0))
    # enforce monotonic ordering with minimum thickness
    names = FORMATION_NAMES
    for i in range(1, len(names)):
        tops[names[i]] = max(tops[names[i]], tops[names[i - 1]] + 60.0)
    return tops


def formation_at_tvd(tvd: float, tops: dict[str, float]) -> str:
    current = FORMATION_NAMES[0]
    for name in FORMATION_NAMES:
        if tvd >= tops[name]:
            current = name
        else:
            break
    return current


def pore_pressure_sg(tvd: float, formation: str, e_km: float, n_km: float) -> float:
    """Toy pore-pressure profile in SG equivalent mud weight."""
    base = 1.03 + 0.000018 * tvd
    if formation in ("Kopili Shale", "Langpar-Lakadong"):
        base += 0.42 * _gauss((e_km - 5.0) ** 2 + (n_km - 8.0) ** 2, 3.5)
    return base


@dataclass
class HoleSection:
    hole_in: str
    casing_in: str
    top_md: float
    shoe_md: float
    mud_type: str
