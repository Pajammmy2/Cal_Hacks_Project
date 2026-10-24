"""OSM extract for a bbox via the Overpass API (cached under engine/.cache/).

Two queries: the walkable/rollable highway network with full node tags (kerbs, crossings, gates),
and the area features the scorer needs (buildings, refuge candidates, vegetation, barriers, addresses, named POIs).
"""
import json

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union
from shapely.validation import make_valid

from . import util

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Spec "Graph build" step 1. highway=steps is added so the steps / step_count fields (step 4) can be true.
HIGHWAYS = ("footway", "path", "sidewalk", "residential", "living_street", "service", "tertiary", "secondary",
            "primary", "unclassified", "pedestrian", "cycleway", "steps")


def _ovp_bbox(bbox):
    w, s, e, n = bbox
    return f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"


def _date_clause(osm_date):
    return f'[date:"{osm_date}"]' if osm_date else ""


def highway_query(bbox, osm_date=None):
    hw = "|".join(HIGHWAYS)
    return (f'[out:json][timeout:300]{_date_clause(osm_date)};'
            f'way["highway"~"^({hw})$"]({_ovp_bbox(bbox)})->.hw;'
            f'.hw out body;node(w.hw);out body;')


def features_query(bbox, osm_date=None):
    b = _ovp_bbox(bbox)
    parts = [
        f'way["building"]({b});relation["building"]({b});',
        f'way["amenity"~"^(parking|hospital)$"]({b});relation["amenity"~"^(parking|hospital)$"]({b});',
        f'way["leisure"~"^(pitch|park|stadium|sports_centre|swimming_pool)$"]({b});'
        f'relation["leisure"~"^(pitch|park|stadium|sports_centre|swimming_pool)$"]({b});',
        f'way["landuse"~"^(farmland|meadow|grass|forest)$"]({b});relation["landuse"~"^(farmland|meadow|grass|forest)$"]({b});',
        f'way["natural"~"^(water|wood|scrub|heath|grassland)$"]({b});'
        f'relation["natural"~"^(water|wood|scrub|heath|grassland)$"]({b});',
        f'way["barrier"]({b});',
        f'nwr["addr:housenumber"]["addr:street"]({b});',
        f'node["name"]["shop"]({b});node["name"]["amenity"]({b});',
    ]
    return f'[out:json][timeout:300]{_date_clause(osm_date)};({"".join(parts)});out geom;'


def overpass(query):
    """Run an Overpass query (cached by query text). Returns parsed JSON."""
    def fetch():
        last = None
        for url in OVERPASS_URLS:
            try:
                return util.http_get(url, method="POST", data={"data": query}, timeout=400, retries=3).content
            except Exception as e:  # try the next mirror
                last = e
        raise last
    raw, _ = util.cached_bytes("overpass", query, "json", fetch)
    data = json.loads(raw)
    if data.get("remark") and "error" in data["remark"].lower():
        raise RuntimeError(f"Overpass error: {data['remark']}")
    return data


def fetch_highways(bbox, osm_date=None):
    """Returns (nodes {id: (lat, lon, tags)}, ways [{id, nodes, tags}], osm_base_timestamp)."""
    d = overpass(highway_query(bbox, osm_date))
    nodes, ways = {}, []
    for el in d["elements"]:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"], el.get("tags") or {})
        elif el["type"] == "way":
            ways.append({"id": el["id"], "nodes": el["nodes"], "tags": el.get("tags") or {}})
    return nodes, ways, d.get("osm3s", {}).get("timestamp_osm_base")


def _ring(coords):
    if len(coords) < 4:
        return None
    try:
        p = Polygon(coords)
    except ValueError:
        return None
    if not p.is_valid:
        p = make_valid(p)
    return p if not p.is_empty and p.area > 0 else None


def _relation_polygon(el):
    outers, inners = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or not m.get("geometry"):
            continue
        line = [(pt["lon"], pt["lat"]) for pt in m["geometry"] if pt]
        if len(line) < 2:
            continue
        (inners if m.get("role") == "inner" else outers).append(LineString(line))
    if not outers:
        return None
    outer = unary_union(list(polygonize(linemerge(outers))))
    if outer.is_empty:
        return None
    if inners:
        inner = unary_union(list(polygonize(linemerge(inners))))
        if not inner.is_empty:
            outer = outer.difference(inner)
    outer = make_valid(outer)
    return outer if not outer.is_empty and outer.area > 0 else None


def element_geometry(el):
    """lon/lat shapely geometry for an `out geom` element: Point, LineString (open way) or (Multi)Polygon."""
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el["type"] == "way":
        g = [(pt["lon"], pt["lat"]) for pt in el.get("geometry", []) if pt]
        if len(g) >= 4 and g[0] == g[-1]:
            return _ring(g)
        return LineString(g) if len(g) >= 2 else None
    if el["type"] == "relation":
        return _relation_polygon(el)
    return None


def fetch_features(bbox, osm_date=None):
    """Returns a list of {osm_type, id, tags, geom (lon/lat)} for every area/line/point feature in the query."""
    d = overpass(features_query(bbox, osm_date))
    out = []
    for el in d["elements"]:
        tags = el.get("tags") or {}
        try:
            g = element_geometry(el)
        except Exception:
            g = None
        if g is None or g.is_empty:
            continue
        out.append({"osm_type": el["type"], "id": el["id"], "tags": tags, "geom": g})
    return out


def load_extra_candidates(path):
    """Reviewed local polygons for places OSM is missing (e.g. a lot mapped only as a point).

    GeoJSON FeatureCollection of Polygon/MultiPolygon features whose properties are OSM-style tags
    (e.g. {"amenity": "parking", "name": "Walgreens"}) plus a required "reviewed_by". They are scored by exactly
    the same rules as OSM features; nothing here can set a score.
    """
    from shapely.geometry import shape
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    out = []
    for n, ft in enumerate(gj.get("features", []), start=1):
        props = dict(ft.get("properties") or {})
        if not props.get("reviewed_by"):
            raise ValueError(f"{path}: feature {n} has no reviewed_by; every extra candidate must be reviewed")
        g = make_valid(shape(ft["geometry"]))
        if g.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{path}: feature {n} is {g.geom_type}; extra candidates must be polygons")
        tags = {k: str(v) for k, v in props.items() if k not in ("reviewed_by", "source", "note")}
        out.append({"osm_type": "local", "id": n, "tags": tags, "geom": g})
    return out
