"""Client profile (CONTRACTS.md client JSON): built from the form or a CSV registry row, validated the same way."""
import csv
import io
import re

MOBILITY = ("manual_chair", "power_chair", "walker", "cane", "bedbound")
TRANSFER = ("independent", "slide_board", "one_person_assist", "two_person_lift", "hoyer")
DEVICES = ("oxygen", "ventilator", "power_chair", "cpap")
VISION = ("normal", "low_vision", "blind")
HEARING = ("normal", "hard_of_hearing", "deaf")
COGNITION = ("none", "simple_steps")
LANGUAGE = ("en", "es", "hmn", "other")

CSV_COLUMNS = (["id", "name", "address", "lat", "lon", "zip", "mobility", "transfer", "devices", "vision", "hearing",
                "cognition", "language", "language_other"]
               + [f"contact{i}_{f}" for i in (1, 2, 3) for f in ("name", "phone", "accessible_vehicle", "distance")]
               + ["sleep_room", "entry", "pets", "chair_location", "zone"])


class ProfileError(ValueError):
    pass


def _s(v):
    return (str(v).strip() if v is not None else "") or None


def _f(v, what):
    v = _s(v)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        raise ProfileError(f"{what} must be a number, got {v!r}")


def _choice(v, allowed, what, default=None):
    v = (_s(v) or default)
    if v is None:
        raise ProfileError(f"{what} is required")
    v = v.lower().replace(" ", "_").replace("-", "_")
    if v not in allowed:
        raise ProfileError(f"{what} must be one of {', '.join(allowed)}; got {v!r}")
    return v


def _yes(v):
    return (_s(v) or "").lower() in ("y", "yes", "true", "1", "on")


def parse_devices(text):
    """'oxygen:4h; power_chair:60%; cpap' -> device list."""
    out = []
    for part in re.split(r"[;|]", text or ""):
        part = part.strip()
        if not part or part.lower() == "none":
            continue
        kind, _, val = part.partition(":")
        kind = _choice(kind, DEVICES, "device")
        val = val.strip().lower().rstrip("h%").strip()
        d = {"kind": kind, "hours": None, "battery_pct": None}
        if val:
            num = _f(val, f"{kind} value")
            if kind == "power_chair":
                d["battery_pct"] = num
            elif kind in ("oxygen", "ventilator"):
                d["hours"] = num
        out.append(d)
    return out


def devices_text(devs):
    parts = []
    for d in devs or []:
        if d.get("kind") == "power_chair" and d.get("battery_pct") is not None:
            parts.append(f"power_chair:{d['battery_pct']:g}%")
        elif d.get("hours") is not None:
            parts.append(f"{d['kind']}:{d['hours']:g}h")
        else:
            parts.append(d["kind"])
    return "; ".join(parts)


def build(m, devices, existing=None):
    """m: flat mapping with CSV_COLUMNS names (minus devices). devices: parsed list."""
    name = _s(m.get("name"))
    if not name:
        raise ProfileError("name is required")
    lat, lon = _f(m.get("lat"), "lat"), _f(m.get("lon"), "lon")
    if (lat is None) != (lon is None):
        raise ProfileError("enter both lat and lon, or neither")
    address = _s(m.get("address"))
    if not address and lat is None:
        raise ProfileError("enter an address or lat/lon")
    lang = _choice(m.get("language"), LANGUAGE, "language", "en")
    if lang == "other" and not _s(m.get("language_other")):
        raise ProfileError("say which language when language is other")
    contacts = []
    for i in (1, 2, 3):
        cn, cp = _s(m.get(f"contact{i}_name")), _s(m.get(f"contact{i}_phone"))
        if cn or cp:
            contacts.append({"name": cn, "phone": cp, "accessible_vehicle": _yes(m.get(f"contact{i}_accessible_vehicle")),
                             "distance": _s(m.get(f"contact{i}_distance"))})
    p = {
        "id": _s(m.get("id")) or (existing or {}).get("id"),
        "name": name, "address": address, "lat": lat, "lon": lon, "zip": _s(m.get("zip")),
        "mobility": _choice(m.get("mobility"), MOBILITY, "mobility"),
        "transfer": _choice(m.get("transfer"), TRANSFER, "transfer", "independent"),
        "devices": devices,
        "vision": _choice(m.get("vision"), VISION, "vision", "normal"),
        "hearing": _choice(m.get("hearing"), HEARING, "hearing", "normal"),
        "cognition": _choice(m.get("cognition"), COGNITION, "cognition", "none"),
        "language": lang, "language_other": _s(m.get("language_other")) if lang == "other" else None,
        "contacts": contacts,
        "home": {"sleep_room": _s(m.get("sleep_room")), "entry": _s(m.get("entry")), "pets": _s(m.get("pets")),
                 "chair_location": _s(m.get("chair_location"))},
        "zone": _s(m.get("zone")),
        "voice": (existing or {}).get("voice") or {"kind": "default"},
    }
    return p


def from_form(form, existing=None):
    devs = []
    for k in DEVICES:
        if _yes(form.get(f"dev_{k}")):
            d = {"kind": k, "hours": None, "battery_pct": None}
            if k in ("oxygen", "ventilator"):
                d["hours"] = _f(form.get(f"dev_{k}_hours"), f"{k} hours")
                if d["hours"] is None:
                    raise ProfileError(f"enter battery hours for the {k}")
            if k == "power_chair":
                d["battery_pct"] = _f(form.get("dev_power_chair_battery_pct"), "power chair battery %")
            devs.append(d)
    return build(form, devs, existing)


def from_csv(text):
    """Returns (profiles, errors[(line, message)])."""
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = [c for c in ("name", "mobility") if c not in (rd.fieldnames or [])]
    if missing:
        return [], [(1, f"missing columns: {', '.join(missing)}")]
    out, errs = [], []
    for i, row in enumerate(rd, start=2):
        try:
            out.append(build(row, parse_devices(row.get("devices"))))
        except ProfileError as e:
            errs.append((i, str(e)))
    return out, errs
