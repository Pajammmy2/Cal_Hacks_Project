"""Builds bundles/<county>/ exactly per CONTRACTS.md, then bundles/<county>.zip. Called by engine/build_bundle.py."""
import json
import shutil
import time
import zipfile
from pathlib import Path

from .core import history
from . import dem as demmod
from . import fuel as fuelmod
from . import graph_build, osm, perimeters, refuges, thumbs, tiles, util, wind

FETCH_MARGIN_DEG = 0.01      # OSM / fuel fetched ~1 km past the bbox so edge refuges see their surroundings
DEM_MARGIN_DEG = 0.015
FRAP_DESC = "CAL FIRE FRAP California Historic Fire Perimeters (ArcGIS FeatureServer)"


def addresses(features):
    out, seen = [], set()
    for f in features:
        t = f["tags"]
        if "addr:housenumber" not in t or "addr:street" not in t:
            continue
        p = f["geom"] if f["geom"].geom_type == "Point" else f["geom"].representative_point()
        key = (t["addr:housenumber"], t["addr:street"], round(p.y, 5), round(p.x, 5))
        if key in seen:
            continue
        seen.add(key)
        out.append({"house_number": t["addr:housenumber"], "street": t["addr:street"], "city": t.get("addr:city", ""),
                    "lat": round(p.y, 7), "lon": round(p.x, 7)})
    return out


def extra_address_rows(csv_path):
    """Rows for addresses.json from a CSV with address,lat,lon (house number + street split off the address)."""
    if not csv_path:
        return []
    import csv, re
    out = []
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^\s*(\S+)\s+(.+?)\s*$", (r.get("address") or "").split(",")[0])
            if not m or not r.get("lat") or not r.get("lon"):
                continue
            out.append({"house_number": m.group(1), "street": m.group(2), "city": r.get("city") or "",
                        "lat": round(float(r["lat"]), 7), "lon": round(float(r["lon"]), 7), "source": "registry"})
    return out


def zip_bundle(bundle_dir):
    bundle_dir = Path(bundle_dir)
    zpath = bundle_dir.parent / f"{bundle_dir.name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bundle_dir.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                z.write(p, Path(bundle_dir.name) / p.relative_to(bundle_dir))
    return zpath


def _prepare_dir(out):
    """Fresh bundle dir, keeping plans/ and audio/ that the staff tool wrote into a previous build."""
    keep = {}
    if out.exists():
        for sub in ("plans", "audio"):
            if (out / sub).exists():
                tmp = out.parent / f".{out.name}_{sub}_{int(time.time())}"
                shutil.move(str(out / sub), tmp)
                keep[sub] = tmp
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for sub, tmp in keep.items():
        shutil.move(str(tmp), out / sub)
    (out / "plans").mkdir(exist_ok=True)
    (out / "audio").mkdir(exist_ok=True)
    if not (out / "audio" / "index.json").exists():
        (out / "audio" / "index.json").write_text("{}")


def build(county, bbox, out_root, extra_addresses=None, fuel_path=None, dem_path=None, perimeters_path=None, current_perimeter=None,
          evidence_path=None, skip_vision=False, fuel_version="LF2024", osm_date=None, min_component_nodes=50,
          extra_candidates=None):
    util.load_env()
    timings, warnings = {}, []
    t_start = time.monotonic()
    bbox = tuple(float(v) for v in bbox)
    fetch_bbox = util.expand_bbox(bbox, FETCH_MARGIN_DEG)
    proj = util.Projector((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    out = Path(out_root) / county
    sources = {}

    with util.stage("osm", timings):
        hw_nodes, hw_ways, osm_ts = osm.fetch_highways(fetch_bbox, osm_date)
        features = osm.fetch_features(fetch_bbox, osm_date)
        if extra_candidates:
            extra = osm.load_extra_candidates(extra_candidates)
            features += extra
            sources["extra_candidates"] = f"{len(extra)} reviewed local polygons from {Path(extra_candidates).name}"
            print(f"  + {len(extra)} reviewed extra candidates from {extra_candidates}")
        sources["osm"] = (f"OpenStreetMap via Overpass API, data as of {osm_date or osm_ts}"
                          + (f" (attic query date {osm_date})" if osm_date else ""))
        print(f"  {len(hw_ways)} highway ways, {len(hw_nodes)} nodes, {len(features)} area/POI features")

    with util.stage("dem", timings):
        if dem_path:
            dem_file = Path(dem_path)
            sources["dem"] = f"local file {dem_file.name}"
        else:
            dem_file = demmod.fetch_3dep(util.expand_bbox(bbox, DEM_MARGIN_DEG))
            sources["dem"] = "USGS 3DEP 1/3 arc-second (3DEPElevation ImageServer exportImage, bilinear)"
        dem = demmod.DEM(dem_file)

    with util.stage("graph", timings):
        graph, gstats = graph_build.build_graph(hw_nodes, hw_ways, dem.sample, clip=fetch_bbox,
                                                min_component_nodes=min_component_nodes)
        print(f"  graph: {gstats}")
        if gstats.get("nodes_without_elevation"):
            warnings.append(f"{gstats['nodes_without_elevation']} graph nodes outside the DEM (elev 0, grade 0)")

    with util.stage("fuel", timings):
        buildings = [((f["osm_type"], f["id"]), f["geom"]) for f in features
                     if "building" in f["tags"] and f["geom"].geom_type in ("Polygon", "MultiPolygon")]
        raster, proxy = None, ()
        try:
            if fuel_path:
                raster = fuelmod.load_local_fuel(fuel_path)
                sources["fuel"] = f"LANDFIRE FBFM40 local file {Path(fuel_path).name}"
            else:
                raster = fuelmod.fetch_landfire(fetch_bbox, fuel_version)
                sources["fuel"] = f"LANDFIRE {fuel_version} FBFM40 (lfps.usgs.gov ImageServer, native 30 m grid)"
        except Exception as e:
            proxy = fuelmod.proxy_polygons(features)
            sources["fuel"] = "osm-proxy"
            msg = (f"LANDFIRE FBFM40 unavailable ({type(e).__name__}: {e}). Using OSM vegetation polygons "
                   f"(landuse=forest, natural=wood|scrub|heath|grassland) as a burnable proxy. d_fuel is NOT "
                   f"LANDFIRE-based.")
            util.warn(msg)
            warnings.append(msg)
        fuel = fuelmod.FuelIndex(proj, buildings, raster_path=raster, proxy_polygons=proxy)
        print(f"  {fuel.cell_count} burnable LANDFIRE cells, {len(buildings)} building footprints, "
              f"{len(proxy)} proxy polygons")

    with util.stage("refuges", timings):
        gates = [(lon, lat) for lat, lon, t in hw_nodes.values() if t.get("barrier") in refuges.GATES]
        ctx = refuges.Context(proj, graph, features, gates)
        cands = refuges.candidates(features, bbox, proj)
        kept, dropped = refuges.score_candidates(cands, ctx, fuel)
        print(f"  {len(cands)} candidates -> {len(kept)} refuges, {len(dropped)} excluded (d_fuel < 15 m)")

    with util.stage("wind", timings):
        w, why = wind.fetch_wind((bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2)
        sources["wind"] = w["source"]
        if why:
            warnings.append(f"wind unavailable: {why}")
            util.warn(f"wind unavailable: {why}")

    built_at = util.now_iso()
    with util.stage("perimeters", timings):
        try:
            if perimeters_path:
                hist = perimeters.load_local(perimeters_path, bbox)
                sources["perimeters"] = f"local file {Path(perimeters_path).name}"
            else:
                hist = perimeters.fetch_frap(bbox)
                sources["perimeters"] = FRAP_DESC
        except Exception as e:
            hist = []
            sources["perimeters"] = "unavailable"
            warnings.append(f"perimeters unavailable: {type(e).__name__}: {e}")
            util.warn(warnings[-1])
        current = (perimeters.load_current(current_perimeter, built_at) if current_perimeter
                   else {"timestamp": built_at, "polygon": None})
        print(f"  {len(hist)} historical perimeter parts")

    with util.stage("write", timings):
        _prepare_dir(out)
        history.apply_to_refuges(kept, hist)
        util.write_json(out / "history.json", history.summary(hist, bbox), indent=1)
        util.write_json(out / "graph.json", graph)
        util.write_json(out / "refuges.json", {"generated_at": built_at, "refuges": kept}, indent=1)
        util.write_json(out / "excluded.json", {"excluded": dropped}, indent=1)
        util.write_json(out / "perimeters.json", {"current": current, "historical": hist})
        util.write_json(out / "wind.json", w, indent=1)
        addrs = addresses(features) + extra_address_rows(extra_addresses)
        util.write_json(out / "addresses.json", addrs)
        if (out / "shared").exists():
            shutil.rmtree(out / "shared")
        shutil.copytree(util.ROOT / "shared", out / "shared")
        if evidence_path:
            shutil.copyfile(evidence_path, out / "evidence.geojson")
        print(f"  {len(addrs)} addresses")

    with util.stage("thumbs", timings):
        counts, placeholder_ids = thumbs.make_thumbs(kept, out / "thumbs")
        sources["thumbs"] = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"
        if counts.get("placeholder"):
            warnings.append(f"{counts['placeholder']} refuge thumbnails are PLACEHOLDERS (no satellite image)")
            util.warn(warnings[-1])

    with util.stage("tiles", timings):
        btags = [(f["tags"], f["geom"]) for f in features
                 if "building" in f["tags"] and f["geom"].geom_type in ("Polygon", "MultiPolygon")]
        tsrc, limitation = tiles.build(out / "tiles.mbtiles", county, bbox, graph, btags, kept)
        sources["tiles"] = tsrc
        if limitation:
            warnings.append(limitation)
            util.warn(limitation)

    manifest = {
        "county": county, "bbox": list(bbox), "built_at": built_at, "sources": sources,
        "counts": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "refuges": len(kept),
                   "excluded": len(dropped), "addresses": len(addrs), "historical_perimeters": len(hist)},
        "version": 1, "placeholder_thumbs": placeholder_ids, "graph_stats": gstats, "warnings": warnings, "timings_s": timings,
    }
    util.write_json(out / "manifest.json", manifest, indent=1)

    if skip_vision:
        manifest["sources"]["vision"] = "skipped (--skip-vision)"
    elif not util.env("ANTHROPIC_API_KEY"):
        manifest["sources"]["vision"] = "skipped (no ANTHROPIC_API_KEY)"
        print("[vision] skipped: ANTHROPIC_API_KEY not set")
    else:
        with util.stage("vision", timings):
            from . import vision
            summary = vision.run(out)
            manifest["sources"]["vision"] = summary["source"]
    timings["total"] = round(time.monotonic() - t_start, 1)
    manifest["timings_s"] = timings
    util.write_json(out / "manifest.json", manifest, indent=1)

    with util.stage("zip", timings):
        z = zip_bundle(out)
    print(f"\nBundle: {out}\nZip:    {z} ({z.stat().st_size / 1e6:.1f} MB)\nTimings (s): {json.dumps(timings)}")
    if warnings:
        print("Warnings:\n  - " + "\n  - ".join(warnings))
    return out
