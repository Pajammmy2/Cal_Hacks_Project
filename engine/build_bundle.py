"""Build one county bundle (spec "Engine spec"; CONTRACTS.md "Bundle").

    python engine/build_bundle.py --county paradise --bbox -121.70,39.70,-121.45,39.86 [--skip-vision]

Optional local inputs replace the network fetches: --fuel FBFM40.tif, --dem dem.tif, --perimeters frap.shp|geojson.
Downloads are cached under engine/.cache/. Keys (ANTHROPIC_API_KEY, MAPBOX_TOKEN, GOOGLE_MAPS_KEY) come from the
environment or the repo-root .env.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ember_engine import bundle, util  # noqa: E402


def parse_bbox(s):
    parts = [float(v) for v in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be w,s,e,n")
    w, s_, e, n = parts
    if not (w < e and s_ < n):
        raise argparse.ArgumentTypeError("bbox must satisfy w < e and s < n")
    return parts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", required=True, help="bundle name, e.g. paradise")
    ap.add_argument("--bbox", required=True, type=parse_bbox, help="w,s,e,n in degrees")
    ap.add_argument("--fuel", help="LANDFIRE FBFM40 GeoTIFF (skips the LANDFIRE download)")
    ap.add_argument("--fuel-version", default="LF2024",
                    help="LANDFIRE version to download when --fuel is not given (e.g. LF2016 for pre-2018 fuels)")
    ap.add_argument("--dem", help="elevation GeoTIFF (skips the 3DEP download)")
    ap.add_argument("--perimeters", help="FRAP fire perimeters (.shp/.geojson/.gpkg); default: FRAP feature service")
    ap.add_argument("--current-perimeter", help="GeoJSON of the current fire perimeter (default: none)")
    ap.add_argument("--evidence", help="Apify actor 1 GeoJSON; copied into the bundle for validate.py")
    ap.add_argument("--osm-date", help="Overpass attic date, e.g. 2018-11-01T00:00:00Z (default: current OSM)")
    ap.add_argument("--min-component-nodes", type=int, default=50,
                    help="drop disconnected graph fragments smaller than this (0 keeps everything)")
    ap.add_argument("--extra-candidates", help="reviewed GeoJSON polygons with OSM-style tags for places OSM is "
                                               "missing (see engine/extra_candidates/README.md)")
    ap.add_argument("--extra-addresses", help="CSV with address,lat,lon columns (e.g. the staff sample registry): "
                    "added to addresses.json so the phone and the staff tool find these homes by address")
    ap.add_argument("--skip-vision", action="store_true", help="do not run the Claude vision pass")
    ap.add_argument("--out", default=str(util.ROOT / "bundles"), help="output root (default: bundles/)")
    argv = list(sys.argv[1:] if argv is None else argv)
    # "--bbox -121.7,..." looks like an option to argparse; glue the value on
    for i, tok in enumerate(argv[:-1]):
        if tok == "--bbox":
            argv[i:i + 2] = [f"--bbox={argv[i + 1]}"]
            break
    a = ap.parse_args(argv)
    if a.county != Path(a.county).name or not a.county:
        ap.error("--county must be a plain name")
    bundle.build(a.county, a.bbox, a.out, extra_addresses=a.extra_addresses, fuel_path=a.fuel, dem_path=a.dem, perimeters_path=a.perimeters,
                 current_perimeter=a.current_perimeter, evidence_path=a.evidence, skip_vision=a.skip_vision,
                 fuel_version=a.fuel_version, osm_date=a.osm_date, min_component_nodes=a.min_component_nodes,
                 extra_candidates=a.extra_candidates)


if __name__ == "__main__":
    main()
