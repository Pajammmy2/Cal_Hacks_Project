"""PG&E outages and PSPS (Public Safety Power Shutoffs): the ArcGIS service behind PG&E's outage map.

Service: https://ags.pge.esriemcs.com/arcgis/rest/services/43/outages/MapServer
  layer 2  PSPS Outage Locations (points)    layer 7  Public Safety Outage Polygon
  layer 4  Outage Locations (points)         layer 8  Outage Polygon
Points and polygons join on OUTAGE_ID. There is no county or ZIP field, so we query by the county
bounding box and keep points inside the county polygon (US Census TIGERweb, bundled), then look up
the ZIP codes (2020 Census ZCTAs, TIGERweb) that each outage polygon (or point) touches.

kind: "psps" for layers 2/7 (cause PUBLIC SAFETY); everything else is "unplanned". PG&E's planned
maintenance outages (cause PLNND SHUTDOWN) are not PSPS, so they land in "unplanned"; `cause`
carries the raw cause for consumers that want to tell them apart.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .common import USER_AGENT, counties, in_county, iso_utc, to_float, url

LAYERS = {"psps": (2, 7), "unplanned": (4, 8)}
FIELDS = "OUTAGE_ID,CURRENT_ETOR,EST_CUSTOMERS,OUTAGE_CAUSE,OUTAGE_START,LAST_UPDATE"


def _envelope(county: dict[str, Any]) -> str:
    w, s, e, n = county["bbox"]
    return json.dumps({"xmin": w, "ymin": s, "xmax": e, "ymax": n, "spatialReference": {"wkid": 4326}})


async def _query(client: httpx.AsyncClient, layer: int, county: dict[str, Any], geometry: bool) -> list[dict]:
    params = {
        "where": "1=1",
        "geometry": _envelope(county),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": FIELDS,
        "returnGeometry": "true" if geometry else "false",
        "outSR": "4326",
        "maxAllowableOffset": "0.0005",
        "f": "json",
    }
    r = await client.get(f"{url('EMBER_PGE_OUTAGE_URL')}/{layer}/query", params=params, timeout=30,
                         headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"layer {layer}: {data['error']}")
    return data.get("features") or []


async def _zips(client: httpx.AsyncClient, geom: dict[str, Any], sem: asyncio.Semaphore) -> list[str]:
    if "rings" in geom:
        g, gtype = {"rings": geom["rings"], "spatialReference": {"wkid": 4326}}, "esriGeometryPolygon"
    else:
        g, gtype = {"x": geom["x"], "y": geom["y"], "spatialReference": {"wkid": 4326}}, "esriGeometryPoint"
    data = {
        "geometry": json.dumps(g),
        "geometryType": gtype,
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ZCTA5",
        "returnGeometry": "false",
        "f": "json",
    }
    async with sem:
        r = await client.post(url("EMBER_ZCTA_URL"), data=data, timeout=20, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(str(body["error"]))
    return sorted({f["attributes"]["ZCTA5"] for f in body.get("features") or [] if f["attributes"].get("ZCTA5")})


async def fetch_outages(client: httpx.AsyncClient, county_name: str) -> tuple[list, list]:
    county = counties()[county_name]
    notes: list[str] = []
    outages: dict[str, dict[str, Any]] = {}
    layer_errors = []

    for kind, (pt_layer, poly_layer) in LAYERS.items():
        try:
            points = await _query(client, pt_layer, county, geometry=True)
        except Exception as exc:
            layer_errors.append(f"{kind} points: {type(exc).__name__}: {exc}")
            continue
        try:
            polys = await _query(client, poly_layer, county, geometry=True)
        except Exception as exc:
            polys = []
            notes.append(f"{kind} polygons unavailable ({type(exc).__name__}); points only")
        rings_by_id: dict[str, list] = {}
        for p in polys:
            oid = str((p.get("attributes") or {}).get("OUTAGE_ID"))
            rings_by_id.setdefault(oid, []).extend((p.get("geometry") or {}).get("rings") or [])
        for f in points:
            a, g = f.get("attributes") or {}, f.get("geometry") or {}
            lon, lat = to_float(g.get("x")), to_float(g.get("y"))
            oid = str(a.get("OUTAGE_ID"))
            if lon is None or lat is None or not in_county(lon, lat, county) or oid in outages:
                continue
            rings = rings_by_id.get(oid) or []
            outages[oid] = {
                "area": {
                    "zips": [],
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in rings]} if rings else None,
                },
                "kind": "psps" if kind == "psps" or (a.get("OUTAGE_CAUSE") or "").upper() == "PUBLIC SAFETY"
                else "unplanned",
                "est_restore": iso_utc(a.get("CURRENT_ETOR")),
                "outage_id": oid,
                "customers": a.get("EST_CUSTOMERS"),
                "cause": a.get("OUTAGE_CAUSE"),
                "_geom": {"rings": rings} if rings else {"x": lon, "y": lat},
            }
    if len(layer_errors) == len(LAYERS):
        raise RuntimeError("; ".join(layer_errors))
    notes += layer_errors

    sem = asyncio.Semaphore(4)
    items = list(outages.values())
    results = await asyncio.gather(*(_zips(client, o["_geom"], sem) for o in items), return_exceptions=True)
    zip_failures = 0
    for o, res in zip(items, results):
        if isinstance(res, BaseException):
            zip_failures += 1
        else:
            o["area"]["zips"] = res
        del o["_geom"]
    if zip_failures:
        notes.append(f"ZIP lookup (Census TIGERweb) failed for {zip_failures} outage(s); lat/lon still given")
    items.sort(key=lambda o: (o["kind"] != "psps", -(o["customers"] or 0)))
    return items, notes
