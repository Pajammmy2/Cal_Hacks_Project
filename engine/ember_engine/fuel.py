"""Fuel distance: LANDFIRE FBFM40 burnable cells (or an OSM vegetation proxy) plus building footprints.

d_fuel = distance from a point to the nearest burnable 30 m cell (as a square, not its centre) or building footprint.
Burnable = any valid FBFM40 code outside the non-burnable set NB1/NB2/NB3/NB8/NB9.
"""
import math

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import Point, Polygon

from . import util

NON_BURNABLE = {91, 92, 93, 98, 99}
LFPS_REST = "https://lfps.usgs.gov/arcgis/rest/services"
LF_GRID_X0, LF_GRID_Y0 = -2362425.0, 3177435.0      # LANDFIRE CONUS grid origin (EPSG:5070), 30 m cells
LF_CELL = 30.0
OSM_PROXY_TAGS = {("landuse", "forest"), ("natural", "wood"), ("natural", "scrub"), ("natural", "heath"),
                  ("natural", "grassland")}


def fetch_landfire(bbox, version="LF2024"):
    """FBFM40 for bbox from the public LANDFIRE ImageServer, on the native 30 m EPSG:5070 grid. Returns local path."""
    t = Transformer.from_crs(4326, 5070, always_xy=True)
    w, s, e, n = bbox
    xs, ys = t.transform([w, e, w, e], [s, s, n, n])
    # snap outward to the LANDFIRE grid so cells are not resampled
    x0 = LF_GRID_X0 + math.floor((min(xs) - LF_GRID_X0) / LF_CELL) * LF_CELL
    x1 = LF_GRID_X0 + math.ceil((max(xs) - LF_GRID_X0) / LF_CELL) * LF_CELL
    y1 = LF_GRID_Y0 - math.floor((LF_GRID_Y0 - max(ys)) / LF_CELL) * LF_CELL
    y0 = LF_GRID_Y0 - math.ceil((LF_GRID_Y0 - min(ys)) / LF_CELL) * LF_CELL
    width, height = int(round((x1 - x0) / LF_CELL)), int(round((y1 - y0) / LF_CELL))
    url = f"{LFPS_REST}/Landfire_{version}/{version}_FBFM40_CONUS/ImageServer/exportImage"
    params = {"bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 5070, "imageSR": 5070, "size": f"{width},{height}",
              "format": "tiff", "pixelType": "S16", "interpolation": "RSP_NearestNeighbor", "f": "image"}
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    def fetch():
        r = util.http_get(url, params=params, timeout=300)
        if not r.content.startswith((b"II*\x00", b"MM\x00*")):
            raise RuntimeError(f"LANDFIRE did not return a GeoTIFF: {r.content[:200]!r}")
        return r.content
    _, path = util.cached_bytes(f"landfire_{version}", key, "tif", fetch)
    return path


class FuelIndex:
    """Nearest-fuel queries in the build's metric CRS (util.Projector)."""

    def __init__(self, proj, buildings=(), raster_path=None, proxy_polygons=()):
        self.proj = proj
        self.source = None
        self.cell_tree = None
        self.cell_count = 0
        if raster_path is not None:
            self._load_raster(raster_path)
        self.proxy = [proj.geom_fwd(g) for g in proxy_polygons]
        self.proxy_tree = STRtree(self.proxy) if self.proxy else None
        # buildings: list of (key, lon/lat polygon)
        self.bkeys = [k for k, _ in buildings]
        self.bgeoms = [proj.geom_fwd(g) for _, g in buildings]
        self.btree = STRtree(self.bgeoms) if self.bgeoms else None

    def _load_raster(self, path):
        with rasterio.open(path) as ds:
            a = ds.read(1)
            nodata = ds.nodata
            tr = ds.transform
            crs = ds.crs
        valid = (a > 0) & (a < 32767)
        if nodata is not None:
            valid &= a != nodata
        burn = valid & ~np.isin(a, list(NON_BURNABLE))
        rows, cols = np.nonzero(burn)
        self.cell_count = int(len(rows))
        self.valid_count = int(valid.sum())
        if not len(rows):
            return
        # cell corners in the raster CRS -> metric CRS, so distance is to the cell square
        to_m = Transformer.from_crs(crs, self.proj.crs, always_xy=True)
        cx, cy = tr * (cols + 0.5, rows + 0.5)
        mx, my = to_m.transform(np.asarray(cx), np.asarray(cy))
        self.cell_xy = np.column_stack([mx, my])
        self.cell_rc = np.column_stack([rows, cols])
        self.cell_tree = cKDTree(self.cell_xy)
        self._tr, self._to_m = tr, to_m
        self.half_diag = math.hypot(abs(tr.a), abs(tr.e)) / 2.0 * 1.01

    def _cell_poly(self, r, c):
        tr = self._tr
        xs, ys = [], []
        for dc, dr in ((0, 0), (1, 0), (1, 1), (0, 1)):
            x, y = tr * (c + dc, r + dr)
            xs.append(x)
            ys.append(y)
        mx, my = self._to_m.transform(xs, ys)
        return Polygon(list(zip(mx, my)))

    def dist_burnable_m(self, x, y):
        best = math.inf
        if self.cell_tree is not None:
            dc, _ = self.cell_tree.query((x, y))
            p = Point(x, y)
            for i in self.cell_tree.query_ball_point((x, y), dc + self.half_diag):
                r, c = self.cell_rc[i]
                best = min(best, self._cell_poly(r, c).distance(p))
        if self.proxy_tree is not None:
            p = Point(x, y)
            i = self.proxy_tree.nearest(p)
            if i is not None:
                best = min(best, self.proxy[int(i)].distance(p))
        return best

    def dist_building_m(self, x, y, exclude_key=None):
        if self.btree is None:
            return math.inf
        p = Point(x, y)
        i = self.btree.nearest(p)
        if i is None:
            return math.inf
        i = int(i)
        if self.bkeys[i] != exclude_key:
            return self.bgeoms[i].distance(p)
        # the nearest is the refuge's own building: look a bit further out
        r = 50.0
        while r < 50000:
            best = math.inf
            for j in self.btree.query(p.buffer(r)):
                j = int(j)
                if self.bkeys[j] != exclude_key:
                    best = min(best, self.bgeoms[j].distance(p))
            if best <= r:                          # anything outside the search disc is farther than r
                return best
            r *= 4
        return math.inf

    def d_fuel(self, x, y, exclude_building=None):
        return min(self.dist_burnable_m(x, y), self.dist_building_m(x, y, exclude_building))


def proxy_polygons(features):
    """OSM vegetation polygons used as a burnable stand-in when LANDFIRE is unavailable."""
    out = []
    for f in features:
        if f["geom"].geom_type not in ("Polygon", "MultiPolygon"):
            continue
        if any(f["tags"].get(k) == v for k, v in OSM_PROXY_TAGS):
            out.append(f["geom"])
    return out


def load_local_fuel(path):
    """--fuel path: any FBFM40 GeoTIFF (clipped) in any CRS."""
    with rasterio.open(path) as ds:
        if ds.count < 1:
            raise ValueError(f"{path}: no bands")
    return path
