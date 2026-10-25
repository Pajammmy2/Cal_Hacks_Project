"""eval/build_dashboard.py: the pieces that must stay truthful (theme colours in sync with Theme.swift, WCAG maths,
the fire-front replay geometry)."""
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_dashboard", REPO / "eval" / "build_dashboard.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)


def test_theme_matches_swift():
    src = (REPO / "navigator" / "Sources" / "EmberApp" / "Theme.swift").read_text()
    for name, rgb in bd.THEME.items():
        m = re.search(rf"static let {name} = Color\(red: ([\d.]+), green: ([\d.]+), blue: ([\d.]+)\)", src)
        if m is None:
            assert name == "text" and "static let text = Color.white" in src
            continue
        assert tuple(float(x) for x in m.groups()) == pytest.approx(rgb), name


def test_contrast_maths_and_aaa():
    assert bd.contrast((1, 1, 1), (0, 0, 0)) == 21.0
    assert bd.contrast((1, 1, 1), (1, 1, 1)) == 1.0
    a = bd.accessibility()
    assert a["all_aaa"], [r for r in a["contrast"] if not r["aaa"]]


def test_front_region_advances_from_the_upwind_side():
    # 10 km square, fire coming from the east (bearing 90): the east edge burns first, the west edge last
    k = 1 / (111320.0 * 0.77)  # ~degrees per metre at 39.7N
    poly = [[-121.60, 39.70], [-121.60 + 10000 * k, 39.70], [-121.60 + 10000 * k, 39.70 + 10000 / 111320.0], [-121.60, 39.70 + 10000 / 111320.0]]
    east = (39.745, -121.60 + 9800 * k)
    west = (39.745, -121.60 + 200 * k)
    h0 = bd.front_region(poly, 90, 0.0, 39.745, -121.60)
    assert not h0(*east) and not h0(*west)
    h1 = bd.front_region(poly, 90, 1, 39.745, -121.60)       # 7.5 km in: east burned, west not yet
    assert h1(*east) and not h1(*west)
    hf = bd.front_region(poly, 90, 1e6, 39.745, -121.60)
    assert hf(*east) and hf(*west)
    assert not hf(39.745, -121.70)                           # outside the polygon never burns


def test_pct():
    assert bd.pct(1, 3) == 33.3 and bd.pct(0, 0) is None
