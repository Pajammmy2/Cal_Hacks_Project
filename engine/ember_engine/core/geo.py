"""Small spherical-geometry helpers shared by the router, the fire-side filter and the scorer."""
import math

EARTH_R = 6371008.8


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, degrees clockwise from north, 0..360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angdiff(a, b):
    """Absolute smallest difference between two bearings, 0..180."""
    d = abs((a - b) % 360.0)
    return 360.0 - d if d > 180.0 else d


def signed_turn(b_in, b_out):
    """Signed bearing change -180..180, positive = right turn."""
    return (b_out - b_in + 540.0) % 360.0 - 180.0


def direction_word(bearing, words):
    return words[int(((bearing % 360.0) + 22.5) // 45.0) % 8]


def _to_xy(lat, lon, lat0):
    k = math.cos(math.radians(lat0))
    return (math.radians(lon) * EARTH_R * k, math.radians(lat) * EARTH_R)


def point_in_polygon(lat, lon, polygon_lonlat):
    inside = False
    n = len(polygon_lonlat)
    j = n - 1
    for i in range(n):
        xi, yi = polygon_lonlat[i]
        xj, yj = polygon_lonlat[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-300) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def distance_to_polygon_edge_m(lat, lon, polygon_lonlat):
    """Distance from a point to the nearest edge of a polygon ring (local equirectangular projection)."""
    px, py = _to_xy(lat, lon, lat)
    best = float("inf")
    n = len(polygon_lonlat)
    for i in range(n):
        ax, ay = _to_xy(polygon_lonlat[i][1], polygon_lonlat[i][0], lat)
        bx, by = _to_xy(polygon_lonlat[(i + 1) % n][1], polygon_lonlat[(i + 1) % n][0], lat)
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - cx, py - cy))
    return best
