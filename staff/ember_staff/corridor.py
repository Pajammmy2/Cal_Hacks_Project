"""Whole-route aerial image for the printed card (owner rule 6b: the card's main map looks like the phone's Choose screen).

One square USGS NAIP export per client covering home -> both refuges, fetched once at print time (keyless, the same source
as the refuge thumbs) and cached in the bundle as corridors/<client_id>.jpg with its footprint in plan["corridor"]. The export
is asked for at most one pixel per 0.6 m (coarser than the service's native ~0.3 m), so nothing is ever upscaled, and at
>= 1200 px for a 2.1 in column it prints above 300 dpi. Offline / failed fetch -> None (the staff UI warns; no placeholder)."""
import io, math
from pathlib import Path
import httpx

USGS_EXPORT = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
NATIVE_M_PER_PX = 0.3        # USGSImageryOnly at its deepest levels (NAIP 0.3-0.6 m)
MIN_M_PER_PX = 0.6           # never ask for more pixels than the ground has
MAX_PX, MIN_PX = 1600, 1200
PAD = 0.14                   # breathing room so pills fit around the Start dot and the refuge
R = 6378137.0


def to3857(lat, lon):
    x = math.radians(lon) * R
    y = math.log(math.tan(math.pi / 4 + math.radians(max(-85.0, min(85.0, lat))) / 2)) * R
    return x, y


def footprint(coords_list, rings):
    """Square web-mercator bbox (xmin, ymin, xmax, ymax) around every route and refuge ring, padded."""
    xs, ys = [], []
    for coords in coords_list:
        for lat, lon in coords:
            x, y = to3857(lat, lon); xs.append(x); ys.append(y)
    for ring in rings:
        for lon, lat in ring:
            x, y = to3857(lat, lon); xs.append(x); ys.append(y)
    if not xs:
        return None
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    side = max(w, h, 120.0) * (1 + 2 * PAD)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)


def pixel_size(bbox):
    side_m = bbox[2] - bbox[0]
    px = int(min(MAX_PX, max(MIN_PX, side_m / MIN_M_PER_PX)))
    return px, side_m / px


def fetch_jpeg(bbox, px, timeout=60.0):
    r = httpx.get(USGS_EXPORT, params={"bbox": ",".join(f"{v:.3f}" for v in bbox), "bboxSR": 3857, "imageSR": 3857,
                                       "size": f"{px},{px}", "format": "jpg", "f": "image"}, timeout=timeout)
    r.raise_for_status()
    if not r.content.startswith(b"\xff\xd8"):
        raise ValueError("USGS export did not return a JPEG")
    return r.content


def project(bbox, px, lat, lon):
    x, y = to3857(lat, lon)
    s = px / (bbox[2] - bbox[0])
    return (round((x - bbox[0]) * s, 1), round((bbox[3] - y) * s, 1))


def ensure(bundle_dir, plan, client_id, fetch=fetch_jpeg):
    """Returns plan["corridor"] (adding and fetching it when missing) or None when imagery cannot be had."""
    choices = plan.get("choices") or []
    if not choices:
        return None
    rings = [c["refuge"].get("polygon") or [] for c in choices[:2]]
    bbox = footprint([c["route"].get("coords") or [] for c in choices[:2]], [r for r in rings if len(r) >= 3])
    if bbox is None:
        return None
    px, mpp = pixel_size(bbox)
    rel = f"corridors/{client_id}.jpg"
    path = Path(bundle_dir) / rel
    meta = plan.get("corridor")
    if meta and meta.get("image") == rel and path.exists() and [round(v, 1) for v in meta["bbox"]] == [round(v, 1) for v in bbox]:
        return meta
    try:
        data = fetch(bbox, px)
    except Exception:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta = {"image": rel, "bbox": [round(v, 3) for v in bbox], "px": px, "m_per_px": round(mpp, 3),
            "native_m_per_px": NATIVE_M_PER_PX, "source": "USGS NAIP (USGSImageryOnly export)"}
    plan["corridor"] = meta
    return meta
