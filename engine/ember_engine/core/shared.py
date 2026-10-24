"""Loads the repo-level shared/*.json contracts (or a bundle's copy of them)."""
import json
from functools import lru_cache
from pathlib import Path

REPO_SHARED = Path(__file__).resolve().parents[3] / "shared"


@lru_cache(maxsize=None)
def load(name, shared_dir=None):
    base = Path(shared_dir) if shared_dir else REPO_SHARED
    with open(base / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def profiles():
    return load("profiles")


def templates():
    return load("turn_templates")


def phrases():
    return load("phrases")


def pronunciation():
    return load("pronunciation")


def intents():
    return load("intents")


def profile_key_for(client):
    """Map a client profile (CONTRACTS.md) to a routing profile key."""
    m = client.get("mobility")
    if m == "manual_chair":
        return "manual_chair"
    if m == "power_chair":
        return "power_chair"
    if m in ("walker", "cane"):
        return "walker"
    if m == "bedbound":
        return "bedbound"
    raise ValueError(f"unknown mobility {m!r}")


def battery_pct_for(client):
    for d in client.get("devices") or []:
        if d.get("kind") == "power_chair" and d.get("battery_pct") is not None:
            return float(d["battery_pct"])
    return 100.0
