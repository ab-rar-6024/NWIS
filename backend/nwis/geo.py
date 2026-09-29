"""Geodesy and well-trajectory helpers."""
from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

import numpy as np

from .config import AREA_LAT0, AREA_LON0

EARTH_R_KM = 6371.0088

_HOLE_SIZE_RE = re.compile(r'^\s*(\d+)(?:[\s-](\d+)\s*/\s*(\d+))?\s*"?\s*$')


def hole_diameter_in(hole: str | None) -> float | None:
    """Parse a driller's hole-size string ('12-1/4"', '17 1/2"', '26"') into decimal inches.

    Returns None for anything that doesn't match — callers decide the fallback, never guess silently here.
    """
    if not hole:
        return None
    m = _HOLE_SIZE_RE.match(hole)
    if not m:
        return None
    whole = float(m.group(1))
    if m.group(2):
        whole += float(m.group(2)) / float(m.group(3))
    return whole


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def latlon_to_km(lat: float, lon: float, lat0: float = AREA_LAT0, lon0: float = AREA_LON0) -> tuple[float, float]:
    """Local equirectangular projection -> (east_km, north_km). Adequate over tens of km."""
    east = math.radians(lon - lon0) * EARTH_R_KM * math.cos(math.radians(lat0))
    north = math.radians(lat - lat0) * EARTH_R_KM
    return east, north


def km_to_latlon(east_km: float, north_km: float, lat0: float = AREA_LAT0, lon0: float = AREA_LON0) -> tuple[float, float]:
    lat = lat0 + math.degrees(north_km / EARTH_R_KM)
    lon = lon0 + math.degrees(east_km / (EARTH_R_KM * math.cos(math.radians(lat0))))
    return lat, lon


def min_curvature(md: Sequence[float], inc_deg: Sequence[float], azi_deg: Sequence[float]):
    """Minimum-curvature survey calculation.

    Returns arrays (tvd, north_m, east_m) relative to the wellhead, one entry per station.
    """
    md = np.asarray(md, float)
    inc = np.radians(np.asarray(inc_deg, float))
    azi = np.radians(np.asarray(azi_deg, float))
    n = len(md)
    tvd = np.zeros(n)
    north = np.zeros(n)
    east = np.zeros(n)
    for i in range(1, n):
        dmd = md[i] - md[i - 1]
        i1, i2 = inc[i - 1], inc[i]
        a1, a2 = azi[i - 1], azi[i]
        cos_dl = math.cos(i2 - i1) - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1))
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)
        rf = 1.0 if dl < 1e-9 else 2.0 / dl * math.tan(dl / 2.0)
        north[i] = north[i - 1] + dmd / 2 * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf
        east[i] = east[i - 1] + dmd / 2 * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf
        tvd[i] = tvd[i - 1] + dmd / 2 * (math.cos(i1) + math.cos(i2)) * rf
    return tvd, north, east


def interp_position(md_q: float, md: np.ndarray, tvd: np.ndarray, north: np.ndarray, east: np.ndarray):
    """Linear interpolation of (tvd, north, east) at a measured depth."""
    return (
        float(np.interp(md_q, md, tvd)),
        float(np.interp(md_q, md, north)),
        float(np.interp(md_q, md, east)),
    )


def md_to_tvd(md_q: float | Iterable[float], md: np.ndarray, tvd: np.ndarray):
    return np.interp(md_q, md, tvd)


def tvd_to_md(tvd_q: float | Iterable[float], md: np.ndarray, tvd: np.ndarray):
    # TVD is monotonic non-decreasing for the wells modelled here.
    return np.interp(tvd_q, tvd, md)
