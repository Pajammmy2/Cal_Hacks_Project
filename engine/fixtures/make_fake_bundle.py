"""Synthetic county bundle `bundles/fake/` so every lane runs end to end without real data.

A 15 x 15 street grid (100 m blocks, split every 50 m) near Paradise, CA, with a hill to the east,
one steep street, a flight of steps, an unpaved lane, a primary road without sidewalks, and eight refuges.

    python engine/fixtures/make_fake_bundle.py [--out bundles/fake]
"""
import argparse
import json
import math
import shutil
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAT0, LON0 = 39.7500, -121.6300
N = 15                 # intersections per side
BLOCK_M = 100.0
DLAT = BLOCK_M / 111320.0
DLON = BLOCK_M / (111320.0 * math.cos(math.radians(LAT0)))

ROW_NAMES = ["Wagstaff Rd", "Bille Rd", "Elliott Rd", "Pearson Rd", "Buschmann Rd", "Foster Rd", "Maxwell Dr",
             "Oliver Rd", "Wayland Rd", "Bennett Rd", "Rocky Ln", "Nunneley Rd", "Copeland Rd", "Lucky John Rd", "Pentz Rd"]
COL_NAMES = ["Skyway", "Clark Rd", "Black Olive Dr", "Almond St", "Fir St", "Elm St", "Birch St", "Willow St",
             "Sawmill Rd", "Neal Rd", "Valley Ridge Dr", "Stark Ln", "Edgewood Ln", "Newall Rd", "Honey Run Rd"]


def elev(i, j):
    # gentle slope up to the east, steeper ridge on the last three columns
    base = 500.0 + j * 2.5
    if j >= 11:
        base += (j - 10) ** 2 * 3.0
    return base + 1.0 * math.sin(i)


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "thumbs").mkdir(parents=True)
    nodes, edges, idx = [], [], {}

    def add_node(lat, lon, z):
        nodes.append({"id": len(nodes), "lat": round(lat, 7), "lon": round(lon, 7), "elev": round(z, 2)})
        return len(nodes) - 1

    for i in range(N):
        for j in range(N):
            idx[(i, j)] = add_node(LAT0 + i * DLAT, LON0 + j * DLON, elev(i, j))

    def street(i1, j1, i2, j2, street_name, **attrs):
        a, b = idx[(i1, j1)], idx[(i2, j2)]
        na, nb = nodes[a], nodes[b]
        mid = add_node((na["lat"] + nb["lat"]) / 2, (na["lon"] + nb["lon"]) / 2, (na["elev"] + nb["elev"]) / 2)
        for x, y in ((a, mid), (mid, b)):
            dz = nodes[y]["elev"] - nodes[x]["elev"]
            e = {"a": x, "b": y, "length_m": 50.0, "grade_pct": round(dz / 50.0 * 100.0, 2), "surface": "paved",
                 "steps": False, "step_count": None, "curb_cut": True, "road_class": "residential",
                 "sidewalk": True, "name": street_name, "driveway": False}
            e.update(attrs)
            edges.append(e)

    for i in range(N):
        for j in range(N - 1):
            attrs = {}
            if i == 7:
                attrs = {"road_class": "primary", "sidewalk": False}          # Oliver Rd: busy, no sidewalk
            if i == 3 and j in (5, 6):
                attrs = {"curb_cut": "unknown"}
            if i == 12 and j == 2:
                attrs = {"surface": "unpaved", "road_class": "service"}
            if i == 2 and j in (4, 5):
                attrs = {"curb_cut": False}                                    # raised kerb, no curb cut
            street(i, j, i, j + 1, ROW_NAMES[i], **attrs)
    for j in range(N):
        for i in range(N - 1):
            attrs = {}
            if j == 1:
                attrs = {"road_class": "secondary"}                            # Clark Rd has sidewalks
            if j == 4 and i == 9:
                attrs = {"steps": True, "step_count": 12, "road_class": "steps", "name": None}
            street(i, j, i + 1, j, COL_NAMES[j], **attrs)

    def node_at(i, j):
        return idx[(i, j)]

    def rect(i, j, di, dj):
        la, lo = LAT0 + i * DLAT, LON0 + j * DLON
        return [[lo, la], [lo + dj * DLON, la], [lo + dj * DLON, la + di * DLAT], [lo, la + di * DLAT], [lo, la]]

    def refuge(rid, name, kind, i, j, terms, claude=None, flag=None):
        poly = rect(i + 0.15, j + 0.15, 0.7, 0.7)
        cx = sum(p[0] for p in poly[:-1]) / 4
        cy = sum(p[1] for p in poly[:-1]) / 4
        ent = node_at(i, j)
        base = round(40 * terms["f_heat"] + 20 * terms["f_area"] + 20 * terms["f_access"] + 10 * terms["f_shelter"] + 10 * terms["f_water"], 1)
        pen = 0.0
        if claude:
            pen = min(30.0, 10.0 * claude["fuel_ring"])
        terms = dict(terms, base_score=base, vision_penalty=pen)
        return {"id": rid, "name": name, "kind": kind, "polygon": poly, "centroid": [cx, cy],
                "entry_points": [{"node": ent, "lat": nodes[ent]["lat"], "lon": nodes[ent]["lon"]}],
                "score": round(base - pen, 1), "terms": terms, "claude": claude, "flag": flag,
                "thumb": f"thumbs/{rid}.jpg"}

    T = lambda d, fh, A, fa, acc, sh, w: {"d_fuel_m": d, "f_heat": fh, "A_clear_m2": A, "f_area": fa, "f_access": acc, "f_shelter": sh, "f_water": w}
    refuges = [
        refuge("r_safeway", "the Safeway lot", "parking", 2, 2, T(60, 1.0, 9000, 0.875, 1.0, 0.5, 0)),
        refuge("r_kmart", "the Kmart lot", "parking", 10, 3, T(70, 1.0, 12000, 1.0, 1.0, 0.5, 0)),
        refuge("r_school", "Ridgeview High School", "building", 6, 9, T(48, 1.0, 6000, 0.5, 1.0, 1.0, 0)),
        refuge("r_lake", "Lake Concow", "water", 13, 12, T(80, 1.0, 20000, 1.0, 0.5, 0.0, 1.0)),
        refuge("r_church", "the church lot", "parking", 4, 12, T(30, 0.5, 4500, 0.3125, 0.5, 0.5, 0),
               claude={"fuel_ring": 2, "clear_area_m2": 3000, "entry": "unsure", "hazards": ["trees on three sides"],
                       "confidence": 0.7, "reason": "Pines touch the lot on the north, east and south edges."}),
        refuge("r_park", "Bille Park", "park", 1, 8, T(40, 0.833, 8000, 0.75, 0.5, 0.0, 0),
               claude={"fuel_ring": 1, "clear_area_m2": 5000, "entry": "yes", "hazards": ["dry grass"],
                       "confidence": 0.4, "reason": "Grass field; edges hard to see under tree cover."}, flag="unsure"),
        refuge("r_walgreens", "the Walgreens lot", "parking", 8, 1, T(55, 1.0, 7000, 0.625, 1.0, 0.5, 0)),
        refuge("r_hospital", "Feather River Hospital campus", "building", 12, 6, T(20, 0.1667, 9000, 0.875, 1.0, 1.0, 0),
               claude={"fuel_ring": 3, "clear_area_m2": 2500, "entry": "yes", "hazards": ["tree ring", "downwind"],
                       "confidence": 0.8, "reason": "Campus is ringed by mature conifers on all sides."}),
    ]

    (out / "graph.json").write_text(json.dumps({"nodes": nodes, "edges": edges}))
    (out / "refuges.json").write_text(json.dumps({"generated_at": "2026-10-23T12:00:00Z", "refuges": refuges}, indent=1))
    (out / "excluded.json").write_text(json.dumps({"excluded": []}))
    camp = rect(11, -6, 6, 5)
    (out / "perimeters.json").write_text(json.dumps({
        "current": {"timestamp": "2026-10-23T12:00:00Z", "polygon": None},
        "historical": [
            {"fire": "Demo fire, hour 0", "timestamp": "2018-11-08T06:30:00Z", "polygon": rect(12, 14, 3, 3)},
            {"fire": "Demo fire, hour 2", "timestamp": "2018-11-08T08:30:00Z", "polygon": rect(9, 11, 6, 6)},
            {"fire": "Demo fire, hour 4", "timestamp": "2018-11-08T10:30:00Z", "polygon": rect(5, 8, 10, 9)},
        ],
        "camp_like": camp}, indent=1))
    (out / "wind.json").write_text(json.dumps({"timestamp": "2026-10-23T12:00:00Z", "direction_from_deg": 45.0,
                                               "speed_mps": 11.0, "source": "fixture"}))
    addrs = []
    for i in range(N):
        for j in range(N):
            addrs.append({"house_number": str(1000 + j * 100 + i), "street": ROW_NAMES[i], "city": "Paradise",
                          "lat": nodes[idx[(i, j)]]["lat"] + DLAT * 0.1, "lon": nodes[idx[(i, j)]]["lon"]})
    (out / "addresses.json").write_text(json.dumps(addrs))

    db = sqlite3.connect(out / "tiles.mbtiles")
    db.executescript("CREATE TABLE metadata (name TEXT, value TEXT);"
                     "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);")
    w, s = LON0, LAT0
    e, n = LON0 + (N - 1) * DLON, LAT0 + (N - 1) * DLAT
    db.executemany("INSERT INTO metadata VALUES (?,?)", [("name", "fake"), ("format", "pbf"), ("bounds", f"{w},{s},{e},{n}"),
                                                          ("minzoom", "12"), ("maxzoom", "16")])
    db.commit()
    db.close()

    try:
        from PIL import Image, ImageDraw
        for r in refuges:
            im = Image.new("RGB", (640, 640), (90, 110, 80))
            d = ImageDraw.Draw(im)
            d.rectangle([120, 120, 520, 520], fill=(150, 150, 150) if r["kind"] != "water" else (60, 90, 150))
            d.text((140, 140), r["name"], fill=(255, 255, 255))
            im.save(out / r["thumb"], "JPEG", quality=80)
    except ImportError:
        pass

    shutil.copytree(ROOT / "shared", out / "shared")
    (out / "plans").mkdir()
    (out / "audio").mkdir()
    (out / "audio" / "index.json").write_text("{}")
    manifest = {"county": "fake", "bbox": [w, s, e, n], "built_at": "2026-10-23T12:00:00Z",
                "sources": {"osm": "synthetic", "dem": "synthetic", "fuel": "synthetic", "perimeters": "synthetic", "wind": "synthetic"},
                "counts": {"nodes": len(nodes), "edges": len(edges), "refuges": len(refuges)}, "version": 1}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    zip_bundle(out)
    return out


def zip_bundle(bundle_dir):
    bundle_dir = Path(bundle_dir)
    zpath = bundle_dir.parent / f"{bundle_dir.name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bundle_dir.rglob("*")):
            if p.is_file():
                z.write(p, Path(bundle_dir.name) / p.relative_to(bundle_dir))
    return zpath


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bundles" / "fake"))
    print(build(ap.parse_args().out))
