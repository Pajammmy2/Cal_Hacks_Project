"""Satellite thumbnails, zoom 18, 640x640 JPEG, one per refuge.

Source order: Mapbox Static (MAPBOX_TOKEN) -> Google Static Maps (GOOGLE_MAPS_KEY) -> USGS National Map
public-domain orthoimagery (no key) -> a clearly labelled placeholder. The source used is recorded in the manifest.
"""
import io
import math
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw
from pyproj import Transformer

from . import util

SIZE = 640
ZOOM = 18
WEB_MERC_M_PER_PX_Z0 = 156543.03392804097
USGS_EXPORT = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
_to3857 = Transformer.from_crs(4326, 3857, always_xy=True)


def _mapbox(lon, lat, token):
    url = (f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon:.6f},{lat:.6f},{ZOOM}/"
           f"{SIZE}x{SIZE}")
    return util.http_get(url, params={"access_token": token, "attribution": "false", "logo": "false"},
                         timeout=30).content


def _google(lon, lat, key):
    return util.http_get("https://maps.googleapis.com/maps/api/staticmap",
                         params={"center": f"{lat:.6f},{lon:.6f}", "zoom": ZOOM, "size": f"{SIZE}x{SIZE}",
                                 "maptype": "satellite", "format": "jpg", "key": key}, timeout=30).content


def _usgs(lon, lat):
    # the same ground footprint as a zoom-18 640 px web-mercator tile view
    x, y = _to3857.transform(lon, lat)
    h = SIZE / 2 * WEB_MERC_M_PER_PX_Z0 / 2 ** ZOOM
    r = util.http_get(USGS_EXPORT, params={"bbox": f"{x - h},{y - h},{x + h},{y + h}", "bboxSR": 3857,
                                           "imageSR": 3857, "size": f"{SIZE},{SIZE}", "format": "jpg",
                                           "f": "image"}, timeout=60)
    if not r.content.startswith(b"\xff\xd8"):
        raise RuntimeError("USGS imagery did not return a JPEG")
    return r.content


def placeholder(name):
    im = Image.new("RGB", (SIZE, SIZE), (70, 70, 70))
    d = ImageDraw.Draw(im)
    d.rectangle([8, 8, SIZE - 9, SIZE - 9], outline=(230, 230, 230), width=4)
    d.line([8, 8, SIZE - 9, SIZE - 9], fill=(120, 120, 120), width=2)
    d.line([8, SIZE - 9, SIZE - 9, 8], fill=(120, 120, 120), width=2)
    d.text((30, 30), "PLACEHOLDER - NO SATELLITE IMAGE", fill=(255, 255, 255))
    d.text((30, 50), "(no MAPBOX_TOKEN / GOOGLE_MAPS_KEY, imagery fetch failed)", fill=(255, 255, 255))
    d.text((30, 80), name[:70], fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _normalize_jpeg(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.size != (SIZE, SIZE):
        im = im.resize((SIZE, SIZE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def make_thumbs(refuges, out_dir, workers=8):
    """Writes thumbs/<id>.jpg for every refuge. Returns ({source: count}, [ids that got a placeholder])."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mapbox, google = util.env("MAPBOX_TOKEN"), util.env("GOOGLE_MAPS_KEY")

    def one(r):
        lon, lat = r["centroid"]
        tries = []
        if mapbox:
            tries.append(("mapbox", lambda: _mapbox(lon, lat, mapbox)))
        if google:
            tries.append(("google", lambda: _google(lon, lat, google)))
        tries.append(("usgs-imagery", lambda: _usgs(lon, lat)))
        for src, fn in tries:
            try:
                key = f"{src}|{lon:.6f},{lat:.6f}|{ZOOM}|{SIZE}"
                data, _ = util.cached_bytes(f"thumb_{src}", key, "jpg", fn)
                (out_dir / f"{r['id']}.jpg").write_bytes(_normalize_jpeg(data))
                return src
            except Exception:
                continue
        (out_dir / f"{r['id']}.jpg").write_bytes(placeholder(r["name"]))
        return "placeholder"

    counts, placeholders = {}, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r, src in zip(refuges, ex.map(one, refuges)):
            counts[src] = counts.get(src, 0) + 1
            if src == "placeholder":
                placeholders.append(r["id"])
    return counts, placeholders
