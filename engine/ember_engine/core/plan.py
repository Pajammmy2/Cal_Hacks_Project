"""Engine call behind POST /plan: {address, profile} -> plan JSON (CONTRACTS.md, Plan JSON).

geocode (local) -> snap to graph -> fire-side filter for the prevailing wind -> route to top five -> best two first.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import cues as cuemod, history
from . import router, shared
from .geocode import Geocoder


class PlanError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class Bundle:
    """A loaded county bundle; cache one per county in long-running servers."""

    def __init__(self, bundle_dir):
        self.dir = Path(bundle_dir)
        self.graph, self.refuges = router.load_bundle(self.dir)
        self.manifest = _read(self.dir / "manifest.json", {})
        self.wind = _read(self.dir / "wind.json")
        self.perimeters = _read(self.dir / "perimeters.json", {"current": None, "historical": []})
        self.geocoder = Geocoder.load(self.dir)

    @property
    def county(self):
        return self.manifest.get("county") or self.dir.name

    def refuge(self, rid):
        return next((r for r in self.refuges if r["id"] == rid), None)


def fire_bearing(bundle, lat=None, lon=None):
    """Pre-season plans use the prevailing wind: the fire is upwind, i.e. toward direction_from.
    Without wind data, the historical prior (history.prior_bearing: where recorded fires came from) is used."""
    if bundle.wind and bundle.wind.get("direction_from_deg") is not None:
        return float(bundle.wind["direction_from_deg"]), "wind"
    hist = (bundle.perimeters or {}).get("historical") or []
    if lat is not None and lon is not None:
        b, _ = history.prior_bearing(lat, lon, hist)
        if b is not None:
            return b, "history"
    return None, "none"


def shelter_steps(client):
    room = ((client.get("home") or {}).get("sleep_room") or "bedroom").strip()
    return room, [
        f"Go to the {room}.",
        "Close every window and door. Close the vents.",
        "Put wet towels under the doors.",
        "Fill the tub with water.",
        "Keep your phone on and where you can see it.",
        f"Call 911. Say: I am in the {room}.",
    ]


def _half_hours(h):
    return math.ceil(h * 2) / 2.0


def _fmt_hours(h):
    return str(int(h)) if float(h).is_integer() else f"{h:.1f}"


def device_sentences(client, route_minutes):
    need = _half_hours(route_minutes / 60.0 + 1.0)
    out = []
    for d in client.get("devices") or []:
        k = d.get("kind")
        if k == "oxygen":
            h = float(d.get("hours") or 0)
            out.append({"kind": k, "hours": h, "sentence":
                        f"Your oxygen battery lasts about {_fmt_hours(h)} hours. If the power goes out, leave while it has {_fmt_hours(need)} {'hour' if need == 1 else 'hours'} left."})
        elif k == "ventilator":
            h = float(d.get("hours") or 0)
            out.append({"kind": k, "hours": h, "sentence":
                        f"Your ventilator battery lasts about {_fmt_hours(h)} hours. If the power goes out, leave while it has {_fmt_hours(need)} {'hour' if need == 1 else 'hours'} left."})
        elif k == "power_chair":
            pct = float(d.get("battery_pct") if d.get("battery_pct") is not None else 100)
            km = shared.profiles()["power_chair"]["full_range_m"] * pct / 100.0 / 1000.0
            out.append({"kind": k, "battery_pct": pct, "sentence":
                        f"Charge your chair every night. At {int(pct)} percent it can go about {int(km)} kilometers."})
        elif k == "cpap":
            out.append({"kind": k, "sentence": "Your CPAP stops when the power goes out. Take it with you."})
    return out


def make_plan(bundle, address, client, blocked=frozenset(), client_id=None):
    if isinstance(bundle, (str, Path)):
        bundle = Bundle(bundle)
    key = shared.profile_key_for(client)
    profile = router.Profile(key, shared.battery_pct_for(client))

    if client.get("lat") is not None and client.get("lon") is not None:
        lat, lon, how, matched = float(client["lat"]), float(client["lon"]), "latlon", f'{client["lat"]},{client["lon"]}'
    else:
        g = bundle.geocoder.geocode(address)
        if g is None:
            raise PlanError(f"Could not find {address!r} in the local address list. Enter lat,lon instead.")
        lat, lon, how, matched = g

    # snap with the most permissive chair-free filter so bedbound clients still get an origin
    snap_profile = profile if not profile.shelter_only else router.Profile("walker")
    node, snap_d = bundle.graph.snap(lat, lon, router.usable_origin(bundle.graph, snap_profile))
    if node is None:
        raise PlanError("No usable path near this address.")

    bearing, bsrc = fire_bearing(bundle, lat, lon)
    prior, prior_from = history.prior_bearing(lat, lon, (bundle.perimeters or {}).get("historical") or [])
    home_history = history.burn_history(lat, lon, (bundle.perimeters or {}).get("historical") or [])
    room, sh_steps = shelter_steps(client)
    choices = []
    perimeter = ((bundle.perimeters or {}).get("current") or {}).get("polygon")
    for c in router.choose(bundle.graph, bundle.refuges, profile, node, bearing, perimeter, blocked):
        cl = cuemod.build_cues(bundle.graph, c["route"], c["refuge"]["name"])
        choices.append({
            "refuge": c["refuge"],
            "route": c["route"],
            "cues": cl,
            "card_steps": cuemod.card_steps(cl),
        })
    if len(choices) >= 2:
        choices[1]["card_steps"] = cuemod.card_steps_after(choices[0]["cues"], choices[1]["cues"])
    minutes = choices[0]["route"]["minutes"] if choices else 0
    return {
        "version": 1,
        "county": bundle.county,
        "client_id": client_id or client.get("id"),
        "generated_at": _now(),
        "origin": {"lat": lat, "lon": lon, "node": node, "snap_m": round(snap_d, 1), "geocode": how, "matched": matched},
        "fire_bearing_deg": bearing,
        "fire_bearing_source": bsrc,
        "history": {"prior_bearing_deg": prior, "prior_from": prior_from, "home_fires": home_history["fires"],
                    "home_recent": home_history["recent"]},
        "profile_key": key,
        "choices": choices,
        "shelter": {"room": room, "steps": sh_steps},
        "devices": device_sentences(client, minutes),
        "no_route": len(choices) == 0,
    }
