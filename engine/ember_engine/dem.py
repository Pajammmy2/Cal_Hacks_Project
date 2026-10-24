"""10 m DEM: USGS 3DEP 1/3 arc-second, fetched as a GeoTIFF for the bbox (or a local --dem file), sampled bilinearly."""
import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform

from . import util

EXPORT_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
ARCSEC_THIRD = 1.0 / 10800.0  # 1/3 arc-second in degrees (~10 m)
MAX_PX = 8000                  # service maxImageWidth / maxImageHeight


def fetch_3dep(bbox):
    """Download 3DEP elevation for bbox at 1/3 arc-second as float32 GeoTIFF (EPSG:4326). Returns local path."""
    w, s, e, n = bbox
    width = int(np.ceil((e - w) / ARCSEC_THIRD))
    height = int(np.ceil((n - s) / ARCSEC_THIRD))
    if width > MAX_PX or height > MAX_PX:
        raise ValueError(f"bbox too large for one 3DEP request ({width}x{height} px > {MAX_PX})")
    params = {
        "bbox": f"{w},{s},{e},{n}", "bboxSR": 4326, "imageSR": 4326, "size": f"{width},{height}",
        "format": "tiff", "pixelType": "F32", "noData": -9999, "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    key = EXPORT_URL + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    def fetch():
        r = util.http_get(EXPORT_URL, params=params, timeout=300)
        if not r.content.startswith((b"II*\x00", b"MM\x00*")):
            raise RuntimeError(f"3DEP did not return a GeoTIFF: {r.content[:200]!r}")
        return r.content
    _, path = util.cached_bytes("dem3dep", key, "tif", fetch)
    return path


class DEM:
    """Bilinear sampler over a single-band elevation raster in any CRS."""

    def __init__(self, path):
        self.path = str(path)
        with rasterio.open(path) as ds:
            self.arr = ds.read(1, masked=True).astype("float64").filled(np.nan)
            self.transform = ds.transform
            self.crs = ds.crs
            self.bounds = ds.bounds
        self._is_geo = self.crs is None or self.crs.to_epsg() == 4326

    def sample(self, lons, lats):
        """Elevation (m) at each lon/lat; NaN outside the raster or on nodata."""
        lons = np.asarray(lons, dtype="float64")
        lats = np.asarray(lats, dtype="float64")
        if self._is_geo:
            xs, ys = lons, lats
        else:
            xs, ys = warp_transform("EPSG:4326", self.crs, lons.tolist(), lats.tolist())
            xs, ys = np.asarray(xs), np.asarray(ys)
        inv = ~self.transform
        cols, rows = inv * (xs, ys)
        # pixel centres sit at +0.5
        c = np.asarray(cols) - 0.5
        r = np.asarray(rows) - 0.5
        c0 = np.floor(c).astype(int)
        r0 = np.floor(r).astype(int)
        fc, fr = c - c0, r - r0
        h, w = self.arr.shape
        c0 = np.clip(c0, 0, w - 1)
        r0 = np.clip(r0, 0, h - 1)
        c1 = np.clip(c0 + 1, 0, w - 1)
        r1 = np.clip(r0 + 1, 0, h - 1)
        a = self.arr
        z = (a[r0, c0] * (1 - fc) * (1 - fr) + a[r0, c1] * fc * (1 - fr)
             + a[r1, c0] * (1 - fc) * fr + a[r1, c1] * fc * fr)
        # a nodata neighbour poisons the bilinear sum: fall back to the nearest pixel there
        near = a[np.clip(np.rint(r).astype(int), 0, h - 1), np.clip(np.rint(c).astype(int), 0, w - 1)]
        z = np.where(np.isnan(z), near, z)
        outside = (c < -0.5) | (r < -0.5) | (c > w - 0.5) | (r > h - 0.5)
        z = np.where(outside, np.nan, z)
        return z
