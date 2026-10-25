"""Historical wildfire input (CONTRACTS.md perimeters.json `historical`: CAL FIRE FRAP perimeters clipped to the bbox).

Two uses, both offline (baked at bundle build, re-derivable from perimeters.json on the phone or in the staff tool):

* `burn_history(lat, lon)`: which recorded perimeters contain a point, and how many since `RECENT_YEAR`.
  Refuge ranking multiplies the base score by `refuge_factor` (a refuge that sat inside two recent perimeters is
  ranked below an otherwise equal one that never burned). The factor is deliberately mild: in Paradise the 2018 Camp
  Fire perimeter covers the whole town, so "has burned" alone cannot separate refuges; the recent count and the
  per-refuge list are what staff see in the review ("why is this ranked down").

* `prior_bearing(lat, lon)`: where fire historically came from, for a phone with no live data. For each recent
  perimeter the bearing from the point to the perimeter's area centroid is weighted by acres and recency; the
  vector mean is the prior. For Paradise this is the Camp Fire axis (ignition at Pulga to the north-east, pushed
  south-west by the Jarbo Gap wind on 2018-11-08), i.e. ENE, which matches the published Camp Fire progression.
  Historical spread direction is not in FRAP; the centroid bearing is the closest reproducible proxy and its
  limitations are stated in the bundle (`history.json` `method`).
"""
import json
import math
import re
from datetime import datetime, timezone

from . import geo

RECENT_YEAR = 2017          # "the past 8 years" as of 2025
RECENT_WINDOW_Y = 8
REFUGE_PENALTY_PER_FIRE = 0.08
REFUGE_PENALTY_MAX = 0.25
NEAR_M = 40000.0            # perimeters whose (unclipped) centroid is farther than this do not shape the prior


def year_of(entry):
    m = re.search(r"\((\d{4})\)", entry.get("fire") or "")
    if m:
        return int(m.group(1))
    ts = entry.get("timestamp") or ""
    return int(ts[:4]) if ts[:4].isdigit() else None


def recent(historical, since=RECENT_YEAR):
    return [h for h in historical or [] if (year_of(h) or 0) >= since and len(h.get("polygon") or []) >= 3]


def centroid(polygon_lonlat):
    """Area-weighted centroid (shoelace) in lon/lat; falls back to the vertex mean for degenerate rings."""
    pts = [p for p in polygon_lonlat if len(p) >= 2]
    a = cx = cy = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-12:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def burn_history(lat, lon, historical):
    """{"fires": [names containing the point, newest first], "recent": count since RECENT_YEAR}."""
    inside = [h for h in historical or [] if len(h.get("polygon") or []) >= 3 and geo.point_in_polygon(lat, lon, h["polygon"])]
    inside.sort(key=lambda h: year_of(h) or 0, reverse=True)
    names = []
    for h in inside:
        if h["fire"] not in names:
            names.append(h["fire"])
    rec = len({h["fire"] for h in inside if (year_of(h) or 0) >= RECENT_YEAR})
    return {"fires": names, "recent": rec}


def refuge_factor(recent_count):
    return 1.0 - min(REFUGE_PENALTY_MAX, REFUGE_PENALTY_PER_FIRE * recent_count)


def prior_bearing(lat, lon, historical, now_year=None):
    """(bearing_deg, [contributing fires]) or (None, []) when no recent perimeter is near the point."""
    now_year = now_year or datetime.now(timezone.utc).year
    vx = vy = 0.0
    used = []
    seen = set()
    for h in recent(historical):
        # Only the unclipped centroid written by the bundle builder is meaningful; a clipped part's centroid is not.
        if not h.get("centroid") or h["fire"] in seen:
            continue
        seen.add(h["fire"])
        clon, clat = h["centroid"]
        d = geo.haversine_m(lat, lon, clat, clon)
        if d > NEAR_M or d < 1.0:
            continue
        age = max(0, now_year - (year_of(h) or now_year))
        w = math.log10(max(float(h.get("acres") or 10.0), 10.0)) * max(0.25, 1.0 - age / (RECENT_WINDOW_Y * 1.5))
        b = math.radians(geo.bearing_deg(lat, lon, clat, clon))
        vx += w * math.sin(b)
        vy += w * math.cos(b)
        used.append({"fire": h["fire"], "bearing_deg": round(geo.bearing_deg(lat, lon, clat, clon), 1),
                     "acres": h.get("acres"), "weight": round(w, 3)})
    if not used or math.hypot(vx, vy) < 1e-9:
        return None, []
    return round(math.degrees(math.atan2(vx, vy)) % 360.0, 1), used


def summary(historical, bbox):
    """history.json for the bundle: recent fires (name, date, acres), the county-centre prior and the method/sources."""
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    fires = []
    for h in recent(historical):
        if any(f["fire"] == h["fire"] for f in fires):
            continue
        fires.append({"fire": h["fire"], "date": (h.get("timestamp") or "")[:10], "acres": h.get("acres")})
    fires.sort(key=lambda f: f["date"], reverse=True)
    bearing, used = prior_bearing(lat, lon, historical)
    return {
        "since": RECENT_YEAR,
        "fires": fires,
        "all_perimeters": len({h["fire"] for h in historical or []}),
        "prior_bearing_deg": bearing,
        "prior_from": used,
        "method": "vector mean over perimeters since %d within %d km of the county centre of the bearing to each "
                  "perimeter's area centroid, weighted by log10(acres) and recency" % (RECENT_YEAR, NEAR_M / 1000),
        "source": "CAL FIRE FRAP California Historic Fire Perimeters (fire25_1 layer), clipped to the county bbox",
    }


def apply_to_refuges(refuges, historical):
    """Adds `history` {fires, recent, factor} to each refuge and multiplies `score` by the factor (base score kept
    in `score_base`). Idempotent: re-running starts from score_base."""
    for r in refuges:
        lon, lat = r["centroid"]
        bh = burn_history(lat, lon, historical)
        f = refuge_factor(bh["recent"])
        base = r.get("score_base", r["score"])
        r["score_base"] = base
        r["score"] = round(base * f, 6)
        r["history"] = {"fires": bh["fires"], "recent": bh["recent"], "factor": round(f, 3)}
    refuges.sort(key=lambda r: (-r["score"], r["id"]))
    return refuges


def apply_to_bundle(bundle_dir):
    """Re-derives history.json and the refuge history factors for an existing bundle (python -m ember_engine.core.history <dir>)."""
    import json
    from pathlib import Path
    d = Path(bundle_dir)
    per = json.loads((d / "perimeters.json").read_text()) if (d / "perimeters.json").exists() else {}
    hist = per.get("historical") or []
    man = json.loads((d / "manifest.json").read_text())
    refs = json.loads((d / "refuges.json").read_text())
    apply_to_refuges(refs["refuges"], hist)
    (d / "refuges.json").write_text(json.dumps(refs, indent=1))
    out = summary(hist, man["bbox"])
    (d / "history.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(apply_to_bundle(sys.argv[1]), indent=1))
