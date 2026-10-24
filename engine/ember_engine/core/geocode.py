"""Local geocoder over the bundle's addresses.json (built from OSM addr:* tags). No external call.

Accepts "lat,lon" directly, an exact "<number> <street>" match, or falls back to the street's
nearest-numbered address (simple interpolation stand-in for Nominatim's).
"""
import json
import re
from pathlib import Path

_LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_ABBR = {
    "road": "rd", "street": "st", "avenue": "ave", "drive": "dr", "lane": "ln", "court": "ct",
    "boulevard": "blvd", "place": "pl", "way": "way", "circle": "cir", "parkway": "pkwy", "highway": "hwy",
    "north": "n", "south": "s", "east": "e", "west": "w", "terrace": "ter", "trail": "trl",
}


def _norm_street(s):
    words = re.sub(r"[^\w\s]", " ", s.lower()).split()
    return " ".join(_ABBR.get(w, w) for w in words)


class Geocoder:
    def __init__(self, addresses):
        self.by_street = {}
        for a in addresses:
            self.by_street.setdefault(_norm_street(a["street"]), []).append(a)

    @classmethod
    def load(cls, bundle_dir):
        p = Path(bundle_dir) / "addresses.json"
        if not p.exists():
            return cls([])
        with open(p, encoding="utf-8") as f:
            return cls(json.load(f))

    def geocode(self, text):
        """Returns (lat, lon, how, matched) or None."""
        m = _LATLON.match(text or "")
        if m:
            return float(m.group(1)), float(m.group(2)), "latlon", text.strip()
        first = (text or "").split(",")[0].strip()
        m = re.match(r"^(\d+)\s+(.+)$", first)
        if not m:
            return None
        num, street = int(m.group(1)), _norm_street(m.group(2))
        cands = self.by_street.get(street)
        if not cands:
            # tolerate a missing suffix ("Clark" vs "Clark Rd")
            keys = [k for k in self.by_street if k.split()[0] == street.split()[0] and (street in k or k in street)]
            if not keys:
                return None
            cands = self.by_street[keys[0]]

        def as_int(a):
            d = re.match(r"\d+", str(a["house_number"]))
            return int(d.group(0)) if d else 10 ** 9

        best = min(cands, key=lambda a: abs(as_int(a) - num))
        how = "address" if as_int(best) == num else "address_nearest"
        return best["lat"], best["lon"], how, f'{best["house_number"]} {best["street"]}'
