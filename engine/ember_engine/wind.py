"""Prevailing wind for pre-season ranking: api.weather.gov points -> gridpoint forecast (CONTRACTS.md wind.json).

direction_from_deg is the speed-weighted vector mean of the hourly forecast wind (direction it blows FROM).
"""
import math
import re
from datetime import datetime, timedelta, timezone

from . import util

NWS = "https://api.weather.gov"
_DUR = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?")


def _hours(valid_time):
    """Expand an NWS validTime 'start/PnDTnHnM' to hourly datetimes."""
    start, dur = valid_time.split("/")
    t0 = datetime.fromisoformat(start)
    m = _DUR.fullmatch(dur)
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    n = max(1, d * 24 + h + (1 if mi else 0))
    return [t0 + timedelta(hours=k) for k in range(n)]


def _series(prop):
    out = {}
    for v in prop.get("values", []):
        if v.get("value") is None:
            continue
        for t in _hours(v["validTime"]):
            out[t] = float(v["value"])
    return out


def _to_mps(value, uom):
    if uom and "km_h" in uom:
        return value / 3.6
    if uom and ("m_s" in uom):
        return value
    if uom and "kt" in uom:
        return value * 0.514444
    if uom and "mi_h" in uom:
        return value * 0.44704
    return value / 3.6                           # NWS gridpoints default to km/h


def prevailing(grid_props):
    dirs = _series(grid_props["windDirection"])
    sp = grid_props.get("windSpeed", {})
    speeds = {t: _to_mps(v, sp.get("uom")) for t, v in _series(sp).items()}
    sx = sy = 0.0
    spd = []
    hours = sorted(dirs)
    for t in hours:
        w = speeds.get(t, 1.0)
        a = math.radians(dirs[t])
        sx += w * math.sin(a)
        sy += w * math.cos(a)
        if t in speeds:
            spd.append(speeds[t])
    if not hours or (sx == 0 and sy == 0):
        return None, None, None, None
    deg = (math.degrees(math.atan2(sx, sy)) + 360.0) % 360.0
    mean_speed = sum(spd) / len(spd) if spd else None
    return deg, mean_speed, hours[0], hours[-1]


def fetch_wind(lat, lon):
    try:
        pts = util.http_get(f"{NWS}/points/{lat:.4f},{lon:.4f}", timeout=20, retries=4,
                            headers={"Accept": "application/geo+json"}).json()
        grid_url = pts["properties"]["forecastGridData"]
        grid = util.http_get(grid_url, timeout=30, retries=4, headers={"Accept": "application/geo+json"}).json()
        props = grid["properties"]
        deg, speed, t0, t1 = prevailing(props)
        if deg is None:
            raise ValueError("no wind values in gridpoint forecast")
        return {
            "timestamp": _iso(props.get("updateTime")) or util.now_iso(),
            "direction_from_deg": round(deg, 1),
            "speed_mps": None if speed is None else round(speed, 1),
            "source": f"api.weather.gov {grid_url.replace(NWS + '/', '')}",
            "forecast_start": _z(t0),
            "forecast_end": _z(t1),
            "method": "speed-weighted vector mean of hourly gridpoint windDirection",
        }, None
    except Exception as e:
        return {"timestamp": util.now_iso(), "direction_from_deg": None, "speed_mps": None,
                "source": "unavailable"}, f"{type(e).__name__}: {e}"


def _z(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _iso(s):
    return _z(datetime.fromisoformat(s)) if s else None
