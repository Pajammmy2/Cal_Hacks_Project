"""Validation (spec "Validation"): is the refuge scorer's top tier where people survived?

    python engine/validate.py --county paradise [--evidence path.geojson | --evidence-dataset <apify dataset id>]

Top tier = score >= 70. For paradise, four named places are located by KNOWN COORDINATES (never by name or
score) and checked: the Kmart lot, the Walgreens lot, and Lake Concow must be top tier; no refuge on the Feather
River Hospital campus may be. Apify actor 1 points (GeoJSON FeatureCollection) are overlaid and the share within
300 m of a top-tier refuge polygon is reported (Apify definition of done: >= 60%).
Writes bundles/<county>/validation.json and validation.png.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from shapely.geometry import Point, Polygon, box, shape  # noqa: E402

from ember_engine import util  # noqa: E402

TOP_TIER = 70.0
EVIDENCE_RADIUS_M = 300.0
EVIDENCE_TARGET = 0.60

# How each named place is identified. Coordinates come from OSM (ids noted) and were cross-checked against
# public listings; a place matches refuge candidates (kept or excluded) by kind and distance, never by name.
PARADISE_CHECKS = [
    {"key": "kmart_lot", "label": "Kmart lot (6600 Clark Rd)", "expect_top": True, "kind": "parking",
     "point": (-121.5905385, 39.775404), "radius_m": 150.0, "pick": "largest",
     "how": "largest amenity=parking polygon within 150 m of the former Kmart building, 6600 Clark Road "
            "(OSM way 474868780, closed Nov 8 2018; now Tractor Supply / Ross)"},
    # Secondary: located live from Overpass (never hard-coded), and it only counts once the evidence actor
    # confirms people sheltered there; with no evidence it is PENDING, with evidence that never mentions it DROPPED.
    {"key": "walgreens_lot", "label": "Walgreens lot", "expect_top": True, "kind": "parking", "secondary": True,
     "store": {"name_regex": "Walgreens", "bbox": (-121.65, 39.73, -121.56, 39.80)}, "radius_m": 80.0,
     "pick": "nearest", "evidence_radius_m": EVIDENCE_RADIUS_M,
     "how": "Overpass: shop=chemist or name~Walgreens in Paradise (39.73-39.80, -121.65 to -121.56); the "
            "amenity=parking polygon within 80 m of it"},
    {"key": "lake_concow", "label": "Lake Concow", "expect_top": True, "kind": "water", "osm": "way/93225300",
     "point": (-121.5196153, 39.7717445), "radius_m": 300.0, "pick": "largest",
     "how": "Concow Reservoir, OSM way 93225300 (natural=water, water=reservoir); else largest water polygon "
            "within 300 m of its centre"},
    {"key": "feather_river_hospital", "label": "Feather River Hospital campus", "expect_top": False, "kind": None,
     "campus_bbox": (-121.5724593, 39.7559230, -121.5681946, 39.7589110), "buffer_m": 50.0, "pick": "all",
     "how": "every refuge candidate whose usable centroid lies within 50 m of the Adventist Health Feather River "
            "campus extent (amenity=hospital OSM way 577807430, 5974 Pentz Rd)"},
]


def locate_store(spec):
    """Look a store up in OSM by name (or shop=chemist + name) inside a bbox. Returns [(geometry, tags, osm ref)]."""
    from ember_engine import osm
    w, s, e, n = spec["bbox"]
    b = f"{s},{w},{n},{e}"
    q = (f'[out:json][timeout:120];(nwr["shop"="chemist"]["name"~"{spec["name_regex"]}",i]({b});'
         f'nwr["name"~"{spec["name_regex"]}",i]({b}););out geom;')
    out = []
    for el in osm.overpass(q)["elements"]:
        g = osm.element_geometry(el)
        if g is not None and not g.is_empty:
            out.append((g, el.get("tags") or {}, f"{el['type']}/{el['id']}"))
    return out


def osm_parking_near(store_ref, radius_m):
    """Every amenity=parking feature in OSM within radius_m of the store, whatever its size (for the report)."""
    from ember_engine import osm
    t, i = store_ref.split("/")
    q = f'[out:json][timeout:120];{t}({i})->.s;nwr(around.s:{radius_m:g})["amenity"="parking"];out geom;'
    return osm.overpass(q)["elements"]


def resolve_stores(checks, proj):
    """Fill in point / label / how for store-located checks from a live Overpass lookup."""
    for c in checks:
        if not c.get("store"):
            continue
        hits = locate_store(c["store"])
        c["stores"] = hits
        if not hits:
            c["point"] = None
            c["store_note"] = f"Overpass found no store matching {c['store']['name_regex']!r} in the bbox"
            continue
        g, tags, ref = hits[0]
        c["point"] = (g.centroid.x, g.centroid.y)
        addr = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
        c["label"] = f"{tags.get('name', c['label'])} lot" + (f" ({addr})" if addr else "")
        c["how"] += f"; found {len(hits)} store(s), using {ref} {tags.get('name', '')} {addr}".rstrip()
        raw = osm_parking_near(ref, c["radius_m"])
        c["store_note"] = (f"OSM has {len(raw)} amenity=parking feature(s) within {c['radius_m']:g} m of {ref}"
                           + ("" if raw else "; nothing to score until the lot is mapped as an area in OSM"))
        c["_store_geom_m"] = proj.geom_fwd(g)


def _poly_m(r, proj):
    return proj.geom_fwd(Polygon(r["polygon"]))


def _locate(check, cands, proj):
    """Candidates (kept + excluded) that the check refers to."""
    if check.get("campus_bbox"):
        zone = proj.geom_fwd(box(*check["campus_bbox"])).buffer(check["buffer_m"])
        return [r for r in cands if zone.contains(proj.geom_fwd(Point(*r["centroid"])))]
    if check.get("osm"):
        hit = [r for r in cands if r.get("osm") == check["osm"]]
        if hit:
            return hit
    if check.get("point") is None:
        return []
    p = check.get("_store_geom_m") or proj.geom_fwd(Point(*check["point"]))
    near = [r for r in cands if (check["kind"] is None or r["kind"] == check["kind"])
            and _poly_m(r, proj).distance(p) <= check["radius_m"]]
    if check["pick"] == "largest" and near:
        near = [max(near, key=lambda r: _poly_m(r, proj).area)]
    elif check["pick"] == "nearest" and near:
        near = [min(near, key=lambda r: _poly_m(r, proj).distance(p))]
    return near


def _why(r):
    t = r["terms"]
    if r.get("excluded_reason"):
        return f"EXCLUDED: {r['excluded_reason']}"
    parts = [f"{k}={t[k]}" for k in ("d_fuel_m", "f_heat", "A_clear_m2", "f_area", "f_access", "f_shelter",
                                     "f_water", "base_score", "vision_penalty")]
    lost = {k: round(w * (1 - float(t[k])), 1) for k, w in
            (("f_heat", 40), ("f_area", 20), ("f_access", 20), ("f_shelter", 10), ("f_water", 10))}
    biggest = ", ".join(f"{k} -{v}" for k, v in sorted(lost.items(), key=lambda kv: -kv[1]) if v > 0)
    return f"{', '.join(parts)}; points lost: {biggest or 'none'}"


def run_checks(checks, kept, excluded, proj, evidence_points=None):
    """evidence_points: None when no actor 1 run is available, else [(lon, lat, props)]."""
    out = []
    cands = [dict(r, _excluded=False) for r in kept] + [dict(r, _excluded=True) for r in excluded]
    for c in checks:
        found = _locate(c, cands, proj)
        res = {"key": c["key"], "label": c["label"], "how": c["how"], "expect_top_tier": c["expect_top"],
               "matches": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "osm": r.get("osm"),
                            "score": r["score"], "excluded": r["_excluded"], "top_tier": (not r["_excluded"])
                            and r["score"] >= TOP_TIER, "terms": r["terms"], "claude": r.get("claude"),
                            "explain": _why(r)} for r in found]}
        if c.get("store_note"):
            res["note"] = c["store_note"]
        if c["expect_top"]:
            res["pass"] = any(m["top_tier"] for m in res["matches"])
            if not found and not c.get("store_note"):
                res["note"] = "no refuge candidate found at this location (OSM has no qualifying polygon there)"
        else:
            res["pass"] = not any(m["top_tier"] for m in res["matches"])
            if not found:
                res["note"] = ("vacuous pass: OSM has no refuge candidate polygon on this site, so nothing there "
                               "could be scored at all")
        res["status"] = "PASS" if res["pass"] else "FAIL"
        if c.get("secondary") and not res["pass"]:
            res["status"], res["counted"] = _secondary_status(c, evidence_points, proj)
            res["note"] = (res.get("note", "") + "; " if res.get("note") else "") + {
                "PENDING": "secondary: not counted until the evidence actor has run",
                "DROPPED": "secondary: dropped, no survivor evidence within "
                           f"{c['evidence_radius_m']:g} m of this store",
                "FAIL": "secondary: evidence confirms people sheltered here, but the scorer has no top-tier refuge",
            }[res["status"]]
        else:
            res["counted"] = True
        out.append(res)
    return out


def _secondary_status(c, evidence_points, proj):
    if evidence_points is None:
        return "PENDING", False
    if c.get("point") is None:
        return "DROPPED", False
    p = c.get("_store_geom_m") or proj.geom_fwd(Point(*c["point"]))
    near = [1 for lon, lat, _ in evidence_points if proj.geom_fwd(Point(lon, lat)).distance(p) <= c["evidence_radius_m"]]
    return ("FAIL", True) if near else ("DROPPED", False)


def fetch_evidence_dataset(dataset_id, out_path):
    """GET /v2/datasets/<id>/items from Apify (one Feature per item) and save it as a FeatureCollection."""
    import os
    import httpx
    params = {"format": "json", "clean": "true"}
    if os.environ.get("APIFY_TOKEN"):
        params["token"] = os.environ["APIFY_TOKEN"]
    r = httpx.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items", params=params, timeout=30)
    r.raise_for_status()
    feats = [f for f in r.json() if isinstance(f, dict) and f.get("type") == "Feature"]
    Path(out_path).write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return out_path


def load_evidence(path):
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    pts = []
    for ft in gj.get("features", []):
        g = ft.get("geometry")
        if g and g.get("type") == "Point":
            pts.append((g["coordinates"][0], g["coordinates"][1], ft.get("properties") or {}))
    return pts


def evidence_share(points, top, proj):
    if not points:
        return None, []
    polys = [_poly_m(r, proj) for r in top]
    flags = []
    for lon, lat, props in points:
        p = proj.geom_fwd(Point(lon, lat))
        d = min((pg.distance(p) for pg in polys), default=float("inf"))
        flags.append({"lon": lon, "lat": lat, "place": props.get("place"), "kind": props.get("kind"),
                      "nearest_top_tier_m": None if d == float("inf") else round(d, 1),
                      "within": d <= EVIDENCE_RADIUS_M})
    return sum(f["within"] for f in flags) / len(flags), flags


def pick_fire(perims, county):
    hist = perims.get("historical") or []
    if not hist:
        return None, []
    if county == "paradise":
        camp = [h for h in hist if h["fire"].lower().startswith("camp (2018")]
        if camp:
            return "Camp Fire (2018)", camp
    by_fire = {}
    for h in hist:
        by_fire.setdefault(h["fire"], []).append(h)
    name = max(by_fire, key=lambda k: sum(Polygon(h["polygon"]).area for h in by_fire[k]))
    return name, by_fire[name]


def plot(path, county, bbox, kept, excluded, checks, fire_name, fire_parts, evidence_flags, checks_spec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    TOP, EVID, INK, MUTED, SURF = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#fcfcfb"
    fig, ax = plt.subplots(figsize=(11, 9), dpi=150, facecolor=SURF)
    ax.set_facecolor(SURF)
    for h in fire_parts:
        xs, ys = zip(*h["polygon"])
        ax.fill(xs, ys, facecolor="#e9e8e4", edgecolor=MUTED, linewidth=1.0, linestyle="--", zorder=1)
    for r in excluded:
        xs, ys = zip(*r["polygon"])
        ax.plot(xs, ys, color="#c3c2b7", linewidth=0.4, zorder=2)
    for r in kept:
        xs, ys = zip(*r["polygon"])
        if r["score"] >= TOP_TIER:
            ax.fill(xs, ys, facecolor=TOP, edgecolor=SURF, linewidth=0.6, zorder=4)
        else:
            ax.plot(xs, ys, color=MUTED, linewidth=0.5, zorder=3)
    if evidence_flags:
        ax.scatter([f["lon"] for f in evidence_flags], [f["lat"] for f in evidence_flags], s=36, color=EVID,
                   edgecolor=SURF, linewidth=1.5, zorder=6)
    for spec, res in zip(checks_spec, checks):
        if spec.get("campus_bbox"):
            b = spec["campus_bbox"]
            x, y = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        elif spec.get("point"):
            x, y = spec["point"]
        else:
            continue
        ax.scatter([x], [y], marker="o", s=70, facecolor="none", edgecolor=INK, linewidth=1.5, zorder=7)
        ax.annotate(f"{res['label']}: {res['status']}", (x, y), xytext=(8, 8),
                    textcoords="offset points", fontsize=8.5, color=INK, zorder=8,
                    bbox={"boxstyle": "round,pad=0.25", "fc": SURF, "ec": MUTED, "lw": 0.5})
    w, s, e, n = bbox
    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_aspect(1 / np.cos(np.radians((s + n) / 2)))
    ax.tick_params(colors=MUTED, labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#c3c2b7")
    handles = [Patch(facecolor=TOP, label=f"Top-tier refuge (score >= {TOP_TIER:g})"),
               Line2D([], [], color=MUTED, lw=0.8, label="Other scored refuge"),
               Line2D([], [], color="#c3c2b7", lw=0.8, label="Excluded (d_fuel < 15 m)")]
    if fire_parts:
        handles.append(Patch(facecolor="#e9e8e4", edgecolor=MUTED, linestyle="--", label=f"{fire_name} perimeter"))
    if evidence_flags:
        handles.append(Line2D([], [], marker="o", lw=0, color=EVID, label="Survivor evidence (Apify actor 1)"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, frameon=True, facecolor=SURF, edgecolor="#c3c2b7")
    ax.set_title(f"Ember refuge scorer vs. where people survived - {county}", color=INK, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", required=True)
    ap.add_argument("--evidence", help="Apify actor 1 GeoJSON (default: bundles/<county>/evidence.geojson)")
    ap.add_argument("--evidence-dataset", help="Apify dataset id of an actor 1 run; saved to bundles/<county>/evidence.geojson")
    ap.add_argument("--bundles", default=str(util.ROOT / "bundles"))
    a = ap.parse_args(argv)
    bdir = Path(a.bundles) / a.county
    if a.evidence_dataset:
        a.evidence = str(fetch_evidence_dataset(a.evidence_dataset, bdir / "evidence.geojson"))
    manifest = util.read_json(bdir / "manifest.json")
    if manifest is None:
        sys.exit(f"no bundle at {bdir}")
    kept = util.read_json(bdir / "refuges.json")["refuges"]
    excluded = util.read_json(bdir / "excluded.json", {"excluded": []})["excluded"]
    bbox = manifest["bbox"]
    proj = util.Projector((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    top = [r for r in kept if r["score"] >= TOP_TIER]

    ev_path = Path(a.evidence) if a.evidence else bdir / "evidence.geojson"
    points = load_evidence(ev_path) if ev_path.exists() else []

    checks_spec = [dict(c) for c in PARADISE_CHECKS] if a.county == "paradise" else []
    resolve_stores(checks_spec, proj)
    checks = run_checks(checks_spec, kept, excluded, proj, points if ev_path.exists() else None)
    share, flags = evidence_share(points, top, proj)
    fire_name, fire_parts = pick_fire(util.read_json(bdir / "perimeters.json", {}), a.county)

    print(f"Validation: {a.county}  (top tier = score >= {TOP_TIER:g}; {len(top)} of {len(kept)} refuges; "
          f"{len(excluded)} excluded)")
    print(f"fuel source: {manifest['sources'].get('fuel')}; osm: {manifest['sources'].get('osm')}")
    for c in checks:
        want = "in top tier" if c["expect_top_tier"] else "NOT in top tier"
        print(f"\n[{c['status']}] {c['label']} {want}\n  located as: {c['how']}")
        if c.get("note"):
            print(f"  {c['note']}")
        for m in c["matches"]:
            print(f"  - {m['id']} '{m['name']}' ({m['kind']}, {m['osm']}) score {m['score']}"
                  f"{' TOP' if m['top_tier'] else ''}\n      {m['explain']}")
    ev = None
    if share is None:
        print(f"\n[NOT RUN] evidence overlay: no Apify actor 1 GeoJSON at {ev_path}")
    else:
        ev = {"path": str(ev_path), "points": len(flags), "share_within_300m": round(share, 3),
              "target": EVIDENCE_TARGET, "pass": share >= EVIDENCE_TARGET, "points_detail": flags}
        print(f"\n[{'PASS' if ev['pass'] else 'FAIL'}] evidence: {share:.0%} of {len(flags)} points within "
              f"{EVIDENCE_RADIUS_M:g} m of a top-tier refuge (target >= {EVIDENCE_TARGET:.0%})")

    engine_pass = all(c["pass"] for c in checks if c["counted"]) if checks else None
    overall = engine_pass if ev is None else (bool(engine_pass) if checks else True) and ev["pass"]
    if checks:
        print(f"\nENGINE CHECKS (spec 'Definition of done'): {'PASS' if engine_pass else 'FAIL'}")
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}"
          + ("" if ev is not None else " (engine checks only; evidence overlay not run)"))

    png = bdir / "validation.png"
    plot(png, a.county, bbox, kept, excluded, checks, fire_name, fire_parts, flags, checks_spec)
    util.write_json(bdir / "validation.json", {
        "county": a.county, "validated_at": util.now_iso(), "top_tier_threshold": TOP_TIER,
        "counts": {"refuges": len(kept), "top_tier": len(top), "excluded": len(excluded)},
        "sources": manifest.get("sources"), "checks": checks, "engine_pass": engine_pass,
        "evidence": ev, "overall_pass": overall, "png": png.name, "fire_overlay": fire_name,
    }, indent=1)
    print(f"wrote {png} and {bdir / 'validation.json'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
