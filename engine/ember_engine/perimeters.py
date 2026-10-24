"""Fire perimeters (CONTRACTS.md perimeters.json): CAL FIRE FRAP historical perimeters intersecting the bbox.

historical = one entry per polygon part (exterior ring, clipped to the bbox plus a margin), oldest first.
current = {"timestamp", "polygon": null} unless a current perimeter file is provided.
"""
import json
from datetime import datetime, timezone

from shapely.geometry import box, shape

from . import util

FRAP_LAYER = ("https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
              "California_Historic_Fire_Perimeters/FeatureServer/0")
CLIP_MARGIN_DEG = 0.05
MIN_PART_DEG2 = 1e-6          # ~1 ha at this latitude: drop slivers


def _ms_to_iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parts(geom):
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon"]
    return []


def _ring(poly):
    return [[round(x, 6), round(y, 6)] for x, y in poly.exterior.coords]


def _entries(features, bbox, name_key, year_key, date_key, acres_key):
    clip = box(*util.expand_bbox(bbox, CLIP_MARGIN_DEG))
    out = []
    for props, geom in features:
        if geom is None or geom.is_empty:
            continue
        g = geom.buffer(0).intersection(clip)
        name = (props.get(name_key) or "Unnamed").strip().title()
        year = props.get(year_key)
        ts = props.get(date_key)
        ts = _ms_to_iso(ts) if isinstance(ts, (int, float)) else (str(ts) if ts else None)
        if ts is None and year:
            ts = f"{int(year)}-01-01T00:00:00Z"
        for p in _parts(g):
            if p.area < MIN_PART_DEG2:
                continue
            out.append({"fire": f"{name} ({int(year)})" if year else name, "timestamp": ts, "polygon": _ring(p),
                        "acres": props.get(acres_key)})
    out.sort(key=lambda e: (e["timestamp"] or "", e["fire"]))
    return out


def fetch_frap(bbox):
    w, s, e, n = bbox
    params = {
        "where": "1=1", "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "FIRE_NAME,YEAR_,ALARM_DATE,CONT_DATE,GIS_ACRES",
        "returnGeometry": "true", "outSR": 4326, "maxAllowableOffset": 0.0001, "geometryPrecision": 6,
        "resultRecordCount": 2000, "f": "geojson",
    }
    url = FRAP_LAYER + "/query"
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    raw, _ = util.cached_bytes("frap", key, "geojson", lambda: util.http_get(url, params=params, timeout=180).content)
    fc = json.loads(raw)
    if "features" not in fc:
        raise RuntimeError(f"FRAP query failed: {raw[:200]!r}")
    feats = [(f.get("properties") or {}, shape(f["geometry"]) if f.get("geometry") else None) for f in fc["features"]]
    return _entries(feats, bbox, "FIRE_NAME", "YEAR_", "ALARM_DATE", "GIS_ACRES")


def load_local(path, bbox):
    """--perimeters path (.shp / .geojson / .gpkg), FRAP field names expected (FIRE_NAME, YEAR_, ALARM_DATE)."""
    import geopandas as gpd
    gdf = gpd.read_file(path)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf = gdf[gdf.intersects(box(*bbox))]
    feats = []
    for _, row in gdf.iterrows():
        props = {k: (None if v != v else v) for k, v in row.drop(labels="geometry").items()}  # NaN -> None
        for k, v in list(props.items()):
            if hasattr(v, "timestamp"):
                props[k] = int(v.timestamp() * 1000)
        feats.append((props, row.geometry))
    return _entries(feats, bbox, "FIRE_NAME", "YEAR_", "ALARM_DATE", "GIS_ACRES")


def load_current(path, built_at):
    """Optional current perimeter GeoJSON: largest polygon's exterior ring; timestamp from properties if present."""
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    best, ts = None, None
    for ft in feats:
        g = shape(ft["geometry"])
        for p in _parts(g):
            if best is None or p.area > best.area:
                best = p
                props = ft.get("properties") or {}
                ts = props.get("timestamp") or props.get("updated") or props.get("date")
    return {"timestamp": ts or built_at, "polygon": _ring(best) if best is not None else None}
