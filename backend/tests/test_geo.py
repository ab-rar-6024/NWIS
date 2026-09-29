from __future__ import annotations

import numpy as np
import pytest

from nwis.geo import haversine_km, hole_diameter_in, km_to_latlon, latlon_to_km, min_curvature


def test_vertical_well_has_tvd_equal_md_and_no_offset():
    md = np.arange(0, 3001, 30.0)
    tvd, n, e = min_curvature(md, np.zeros_like(md), np.zeros_like(md))
    assert np.allclose(tvd, md) and np.allclose(n, 0) and np.allclose(e, 0)


def test_tangent_section_geometry():
    md = np.arange(0, 1001, 10.0)
    tvd, n, e = min_curvature(md, np.full_like(md, 90.0), np.zeros_like(md))  # horizontal, heading north
    assert np.allclose(tvd, 0, atol=1e-6) and abs(n[-1] - 1000) < 1e-6 and abs(e[-1]) < 1e-6
    tvd, n, e = min_curvature(md, np.full_like(md, 30.0), np.full_like(md, 90.0))  # 30 deg, heading east
    assert abs(tvd[-1] - 1000 * np.cos(np.radians(30))) < 1e-6 and abs(e[-1] - 1000 * np.sin(np.radians(30))) < 1e-6


def test_haversine_and_projection_roundtrip():
    assert abs(haversine_km(27.0, 95.0, 28.0, 95.0) - 111.19) < 0.2
    e, n = latlon_to_km(27.35, 95.42)
    lat, lon = km_to_latlon(e, n)
    assert abs(lat - 27.35) < 1e-9 and abs(lon - 95.42) < 1e-9
    assert abs(haversine_km(27.30, 95.35, 27.35, 95.42) - float(np.hypot(e, n))) < 0.05


@pytest.mark.parametrize("hole,expected", [
    ('20"', 20.0), ('13-3/8"', 13.375), ('17-1/2"', 17.5), ('9-5/8"', 9.625),
    ('12-1/4"', 12.25), ('7"', 7.0), ('8-1/2"', 8.5), ('17 1/2"', 17.5),
])
def test_hole_diameter_parses_standard_bit_sizes(hole, expected):
    assert hole_diameter_in(hole) == pytest.approx(expected)


@pytest.mark.parametrize("hole", [None, "", "garbage", "twelve inches"])
def test_hole_diameter_returns_none_for_unparseable_input(hole):
    assert hole_diameter_in(hole) is None
