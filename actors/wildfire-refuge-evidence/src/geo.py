"""Geography: fire perimeter centroid (CAL FIRE FRAP / NIFC), Nominatim geocoding, 50 km filter,
150 m clustering."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from collections import Counter
from typing import Any

import httpx

log = logging.getLogger(__name__)

EARTH_R_M = 6_371_008.8
RADIUS_KM = 50.0
CLUSTER_M = 150.0

FRAP_URL = os.environ.get(
    "EMBER_FRAP_URL",
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
    "California_Historic_Fire_Perimeters/FeatureServer/0/query",
)
NIFC_URL = os.environ.get(
    "EMBER_NIFC_URL",
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query",
)
NOMINATIM_URL = os.environ.get("EMBER_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
USER_AGENT = "Ember-wildfire-refuge-evidence/1.0 (Apify actor; https://apify.com/store)"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- perimeter centroid

def normalize_fire_name(fire_name: str) -> str:
    """'Camp Fire' -> 'CAMP'; 'August Complex' -> 'AUGUST COMPLEX' kept as-is besides 'FIRE'."""
    name = re.sub(r"[^A-Za-z0-9 \-']", " ", fire_name).upper()
    name = re.sub(r"\bFIRE\b", " ", name)
    return " ".join(name.split())


def _sql_quote(s: str) -> str:
    return s.replace("'", "''")


def rings_centroid(rings: list[list[list[float]]]) -> tuple[float, float] | None:
    """Area-weighted centroid (lat, lon) of polygon rings given as [[lon, lat], ...]."""
    a_sum = cx = cy = 0.0
    for ring in rings:
        n = len(ring)
        for i in range(n - 1 if ring[0] == ring[-1] else n):
            x0, y0 = ring[i][0], ring[i][1]
            x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            cross = x0 * y1 - x1 * y0
            a_sum += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
    if abs(a_sum) < 1e-12:
        pts = [p for r in rings for p in r]
        if not pts:
            return None
        return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)
    return cy / (3 * a_sum), cx / (3 * a_sum)


async def _query_perimeter(client: httpx.AsyncClient, url: str, where: str, acres_field: str) -> dict | None:
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": "0.005",
        "f": "json",
    }
    r = await client.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    feats = [f for f in data.get("features", []) if (f.get("geometry") or {}).get("rings")]
    if not feats:
        return None
    return max(feats, key=lambda f: (f.get("attributes") or {}).get(acres_field) or 0)


async def find_perimeter_centroid(
    client: httpx.AsyncClient, fire_name: str, year: int
) -> tuple[tuple[float, float] | None, str]:
    """Return ((lat, lon) | None, note). Tries CAL FIRE FRAP first, then NIFC."""
    name = _sql_quote(normalize_fire_name(fire_name))
    if not name:
        return None, "perimeter filter skipped: empty fire name"
    attempts = [
        ("CAL FIRE FRAP", FRAP_URL, f"UPPER(FIRE_NAME) = '{name}' AND YEAR_ = {int(year)}", "GIS_ACRES"),
        ("NIFC", NIFC_URL, f"UPPER(INCIDENT) = '{name}' AND FIRE_YEAR_INT = {int(year)}", "GIS_ACRES"),
    ]
    errors = []
    for label, url, where, acres in attempts:
        try:
            feat = await _query_perimeter(client, url, where, acres)
        except Exception as exc:  # network / service error -> try next source
            errors.append(f"{label}: {exc}")
            continue
        if feat:
            c = rings_centroid(feat["geometry"]["rings"])
            if c:
                return c, f"perimeter centroid from {label} ({c[0]:.4f}, {c[1]:.4f}); 50 km filter applied"
        errors.append(f"{label}: no perimeter for {name} {year}")
    return None, "perimeter filter skipped (" + "; ".join(errors) + ")"


# ---------------------------------------------------------------- geocoding

SETTLEMENT_TYPES = {
    "country", "state", "region", "province", "county", "district", "municipality", "city", "town",
    "village", "hamlet", "suburb", "borough", "postcode", "neighbourhood", "quarter", "locality",
}


def is_specific_result(r: dict[str, Any]) -> bool:
    """Reject admin areas / settlements: a town centroid is not a place where people sheltered."""
    if r.get("category") == "boundary" or r.get("class") == "boundary":
        return False
    return (r.get("addresstype") or r.get("type")) not in SETTLEMENT_TYPES


class Geocoder:
    """Nominatim search: 1 request/second, identifying User-Agent, cached by query."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        region_hint: str | None = None,
        center: tuple[float, float] | None = None,
        countrycodes: str | None = None,
        cache: dict[str, Any] | None = None,
        min_interval_s: float = 1.0,
        email: str | None = None,
    ):
        self.client = client
        self.region_hint = (region_hint or "").strip() or None
        self.center = center
        self.countrycodes = countrycodes
        self.cache: dict[str, Any] = cache if cache is not None else {}
        self.min_interval_s = min_interval_s
        self.email = email or os.environ.get("NOMINATIM_EMAIL")
        self._lock = asyncio.Lock()
        self._last = 0.0
        self.requests = 0

    def _params(self, q: str) -> dict[str, str]:
        p = {"q": q, "format": "jsonv2", "limit": "5", "addressdetails": "0"}
        if self.countrycodes:
            p["countrycodes"] = self.countrycodes
        if self.center:
            lat, lon = self.center
            dlat = RADIUS_KM / 111.0
            dlon = RADIUS_KM / (111.0 * max(0.2, math.cos(math.radians(lat))))
            # viewbox=left,top,right,bottom; bounded=0 -> bias, not a hard limit
            p["viewbox"] = f"{lon - dlon:.4f},{lat + dlat:.4f},{lon + dlon:.4f},{lat - dlat:.4f}"
            p["bounded"] = "0"
        if self.email:
            p["email"] = self.email
        return p

    async def _search(self, q: str) -> tuple[float, float] | None:
        key = q.lower()
        if key in self.cache:
            hit = self.cache[key]
            return (hit[0], hit[1]) if hit else None
        async with self._lock:
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                r = await self.client.get(
                    NOMINATIM_URL, params=self._params(q), headers={"User-Agent": USER_AGENT}, timeout=20
                )
            finally:
                self._last = time.monotonic()
                self.requests += 1
        if r.status_code != 200:
            log.warning("Nominatim HTTP %s for %r", r.status_code, q)
            return None  # not cached: transient
        results = [(float(x["lat"]), float(x["lon"])) for x in r.json() if is_specific_result(x)]
        if results and self.center:
            # Chains ("Walgreens", "Kmart") match many stores: take the one nearest the fire.
            results.sort(key=lambda p: haversine_m(p[0], p[1], self.center[0], self.center[1]))
        hit = results[0] if results else None
        self.cache[key] = list(hit) if hit else None
        return hit

    async def geocode(self, place: str) -> tuple[float, float] | None:
        """Try each name variant with the region_hint suffix, then bare (viewbox bias still applies)."""
        queries: list[str] = []
        for v in query_variants(place):
            if self.region_hint and self.region_hint.lower() not in v.lower():
                queries.append(f"{v}, {self.region_hint}")
            queries.append(v)
        for q in dict.fromkeys(queries).keys():  # dedupe, keep order
            if len(q) < 3:
                continue
            hit = await self._search(q)
            if hit:
                return hit
        return None


_GENERIC = re.compile(r"\b(the|parking lot|parking area|parking|lot|area|grounds)\b", re.I)
_SPLIT = re.compile(r"\s+(?:on|off|near|at|in|along|by|behind|next to)\s+", re.I)


def query_variants(place: str, limit: int = 4) -> list[str]:
    """Ordered Nominatim query variants for a place phrase extracted from prose.

    "Kmart parking lot on Clark Road" -> ["Kmart parking lot on Clark Road", "Kmart on Clark Road",
    "Kmart", "Clark Road"]; "Lake Concow" -> ["Lake Concow", "Concow Reservoir", "Concow Lake"].
    """
    place = " ".join(place.split())
    out = [place]
    stripped = " ".join(_GENERIC.sub(" ", place).split())
    if stripped and stripped != place:
        out.append(stripped)
    parts = [p.strip() for p in _SPLIT.split(stripped or place) if p.strip()]
    # Head name ("Kmart" from "Kmart on Clark Road") only if it is a proper name, not "field".
    if len(parts) > 1 and re.search(r"\b[A-Z][A-Za-z'&.-]+", parts[0]):
        out.append(parts[0])
    m = re.fullmatch(r"(?:Lake\s+(.+)|(.+?)\s+Lake)", stripped or place, re.I)
    if m:
        name = m.group(1) or m.group(2)
        out += [f"{name} Reservoir", f"Lake {name}" if m.group(2) else f"{name} Lake"]
    # Deliberately no road-only / town-only fallback: a town centroid is worse than no point.
    return list(dict.fromkeys(o for o in out if o))[:limit]


def within_radius(point: tuple[float, float], center: tuple[float, float] | None, km: float = RADIUS_KM) -> bool:
    if center is None:
        return True
    return haversine_m(point[0], point[1], center[0], center[1]) <= km * 1000


# ---------------------------------------------------------------- clustering

def cluster_points(points: list[dict[str, Any]], radius_m: float = CLUSTER_M) -> list[list[dict[str, Any]]]:
    """Single-linkage clustering: points within `radius_m` of any member join the cluster."""
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if haversine_m(points[i]["lat"], points[i]["lon"], points[j]["lat"], points[j]["lon"]) <= radius_m:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, p in enumerate(points):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())


def _most_common(values: list[str]) -> str:
    counts = Counter(values)
    best = max(counts.values())
    return next(v for v in values if counts[v] == best)  # ties -> first seen


def clusters_to_features(clusters: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each member: {lat, lon, place, kind, quote: {text, url, outlet, date}}."""
    features = []
    for members in clusters:
        lat = sum(m["lat"] for m in members) / len(members)
        lon = sum(m["lon"] for m in members) / len(members)
        quotes, seen = [], set()
        for m in members:
            q = m["quote"]
            k = (q["text"], q["url"])
            if k not in seen:
                seen.add(k)
                quotes.append(q)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "place": _most_common([m["place"] for m in members]),
                "kind": _most_common([m["kind"] for m in members]),
                "quotes": quotes,
                "mentions": len(quotes),  # distinct (quote, url) mentions in the cluster
            },
        })
    features.sort(key=lambda f: (-f["properties"]["mentions"], f["properties"]["place"]))
    return features
