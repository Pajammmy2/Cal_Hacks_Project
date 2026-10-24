"""Regenerate src/data/ca_counties.json (run once by a developer, not by the actor).

For each of California's 58 counties it stores:
  - bbox [w, s, e, n] and a generalized outer polygon (US Census TIGERweb, ~500 m tolerance)
  - caltrans_districts: which Caltrans LCS district feeds to read
  - genasys_prefix: the Zonehaven/Genasys zone identifier prefix (US-CA-<prefix>-...) or null
    when the county has no zones in Genasys Protect.

The Genasys prefix table was discovered on 2026-10-23 by listing every `US-CA-*` zone in the
public Zonehaven WFS and resolving one zone per prefix through api-aware.zonehaven.com/v2/zone
(the `countyName` field). Re-run that discovery if a county joins Genasys Protect.

Usage:  python scripts/build_counties.py
"""

from __future__ import annotations

import json
import pathlib

import httpx

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"

# Caltrans district(s) per county. Kern is split between D6 and D9; Solano closures also appear in D3.
DISTRICTS: dict[str, list[int]] = {
    "Del Norte": [1], "Humboldt": [1], "Lake": [1], "Mendocino": [1],
    "Lassen": [2], "Modoc": [2], "Plumas": [2], "Shasta": [2], "Siskiyou": [2], "Tehama": [2], "Trinity": [2],
    "Butte": [3], "Colusa": [3], "El Dorado": [3], "Glenn": [3], "Nevada": [3], "Placer": [3],
    "Sacramento": [3], "Sierra": [3], "Sutter": [3], "Yolo": [3], "Yuba": [3],
    "Alameda": [4], "Contra Costa": [4], "Marin": [4], "Napa": [4], "San Francisco": [4],
    "San Mateo": [4], "Santa Clara": [4], "Solano": [4, 3], "Sonoma": [4],
    "Monterey": [5], "San Benito": [5], "San Luis Obispo": [5], "Santa Barbara": [5], "Santa Cruz": [5],
    "Fresno": [6], "Kern": [6, 9], "Kings": [6], "Madera": [6], "Tulare": [6],
    "Los Angeles": [7], "Ventura": [7],
    "Riverside": [8], "San Bernardino": [8],
    "Inyo": [9], "Mono": [9],
    "Alpine": [10], "Amador": [10], "Calaveras": [10], "Mariposa": [10], "Merced": [10],
    "San Joaquin": [10], "Stanislaus": [10], "Tuolumne": [10],
    "Imperial": [11], "San Diego": [11],
    "Orange": [12],
}

GENASYS: dict[str, str] = {
    "Alameda": "XAL", "San Bernardino": "XBO", "Calaveras": "XCA", "Contra Costa": "XCC",
    "Santa Cruz": "XCZ", "Del Norte": "XDN", "Fresno": "XFR", "Humboldt": "XHU", "Inyo": "XIN",
    "Kern": "XKE", "Los Angeles": "XLA", "Lake": "XLK", "Lassen": "XLS", "Madera": "XMA",
    "Mendocino": "XME", "Mono": "XMN", "Modoc": "XMO", "Marin": "XMR", "Monterey": "XMY",
    "Napa": "XNA", "Nevada": "XNE", "Orange": "XOR", "Plumas": "XPU", "Riverside": "XRI",
    "Santa Barbara": "XSB", "Santa Clara": "XSC", "San Diego": "XSD", "San Francisco": "XSF",
    "Shasta": "XSH", "Sierra": "XSI", "Siskiyou": "XSK", "San Luis Obispo": "XSL",
    "San Mateo": "XSM", "Solano": "XSO", "Sutter": "XSU", "Tehama": "XTE", "Trinity": "XTR",
    "Tulare": "XTU", "Ventura": "XVE", "Yolo": "XYO", "Yuba": "XYU",
}


def main() -> None:
    params = {
        "where": "STATE='06'",
        "outFields": "BASENAME,GEOID",
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": "0.005",
        "geometryPrecision": "4",
        "f": "json",
    }
    r = httpx.get(TIGER, params=params, timeout=120)
    r.raise_for_status()
    out = {}
    for feat in r.json()["features"]:
        name = feat["attributes"]["BASENAME"]
        rings = feat["geometry"]["rings"]
        ring = max(rings, key=len)  # outer ring; islands (e.g. Channel Islands) dropped
        xs = [p[0] for r_ in rings for p in r_]
        ys = [p[1] for r_ in rings for p in r_]
        out[name] = {
            "geoid": feat["attributes"]["GEOID"],
            "bbox": [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)],
            "polygon": rings if len(rings) > 1 else [ring],
            "caltrans_districts": DISTRICTS[name],
            "genasys_prefix": GENASYS.get(name),
        }
    assert len(out) == 58, len(out)
    path = pathlib.Path(__file__).resolve().parents[1] / "src" / "data" / "ca_counties.json"
    path.write_text(json.dumps(dict(sorted(out.items())), separators=(",", ":")))
    print(f"wrote {path} ({path.stat().st_size} bytes, {len(out)} counties)")


if __name__ == "__main__":
    main()
