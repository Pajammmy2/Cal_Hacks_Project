"""Shared helpers for the bundle build: cached HTTP, metric projections, timers, JSON output."""
import hashlib
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pyproj import CRS, Transformer

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = ENGINE_DIR.parent
CACHE_DIR = ENGINE_DIR / ".cache"
USER_AGENT = "ember-build/0.1 (wildfire refuge bundle builder; pre-season)"


def load_env():
    """Load repo-root .env if python-dotenv is present. Keys are only ever read from the environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def warn(msg):
    print(f"\n!!! WARNING: {msg}\n", file=sys.stderr, flush=True)


@contextmanager
def stage(name, timings):
    t0 = time.monotonic()
    print(f"[{name}] ...", flush=True)
    try:
        yield
    finally:
        dt = time.monotonic() - t0
        timings[name] = round(dt, 1)
        print(f"[{name}] done in {dt:.1f} s", flush=True)


def cache_path(kind, key, ext):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{kind}_{h}.{ext}"


def http_get(url, params=None, timeout=60.0, retries=3, headers=None, method="GET", data=None):
    """GET/POST with retries and backoff (pre-season build, not fire-day code). Returns httpx.Response or raises."""
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=True, headers=h) as c:
                r = c.request(method, url, params=params, data=data)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.HTTPError, OSError) as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(2.0 * (attempt + 1) ** 2)
    raise last


def cached_bytes(kind, key, ext, fetch):
    """Return cached bytes for `key`, calling fetch() -> bytes on a miss."""
    p = cache_path(kind, key, ext)
    if p.exists() and p.stat().st_size > 0:
        return p.read_bytes(), p
    data = fetch()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    return data, p


def utm_crs(lon, lat):
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


class Projector:
    """lon/lat <-> local UTM metres. All areas, buffers and distances in the build use this."""

    def __init__(self, lon, lat):
        self.crs = utm_crs(lon, lat)
        self._fwd = Transformer.from_crs(4326, self.crs, always_xy=True)
        self._inv = Transformer.from_crs(self.crs, 4326, always_xy=True)

    def fwd(self, lon, lat):
        return self._fwd.transform(lon, lat)

    def inv(self, x, y):
        return self._inv.transform(x, y)

    def geom_fwd(self, g):
        return _apply(self._fwd, g)

    def geom_inv(self, g):
        return _apply(self._inv, g)


def _apply(tr, g):
    import numpy as np
    import shapely
    return shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


def expand_bbox(bbox, margin_deg):
    w, s, e, n = bbox
    return (w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg)


def write_json(path, obj, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False, separators=None if indent else (",", ":"))
    tmp.replace(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def env(name, default=None):
    v = os.environ.get(name)
    return v if v else default
