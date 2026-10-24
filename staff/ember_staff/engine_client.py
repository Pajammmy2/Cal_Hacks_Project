"""Engine call: {address, profile} -> plan JSON (CONTRACTS.md). In-process by default; EMBER_ENGINE_URL -> POST <url>/plan."""
import threading

import httpx

from . import config
from ember_engine.core import plan as coreplan  # noqa: E402  (config put engine/ on sys.path)

_bundles = {}
_lock = threading.Lock()


class EngineError(Exception):
    pass


def bundle(county=None):
    """Loaded core Bundle, cached per county directory (reloaded if graph.json changed)."""
    d = config.bundle_dir(county)
    if not (d / "graph.json").exists():
        raise EngineError(f"No bundle at {d}. Build it first (engine/build_bundle.py or engine/fixtures/make_fake_bundle.py).")
    key = str(d)
    mtime = (d / "graph.json").stat().st_mtime
    with _lock:
        hit = _bundles.get(key)
        if hit is None or hit[0] != mtime:
            hit = (mtime, coreplan.Bundle(d))
            _bundles[key] = hit
        return hit[1]


def engine_input(profile):
    """The profile as the engine expects it (CONTRACTS.md client JSON)."""
    return {k: v for k, v in profile.items() if k != "voice"}


def run_plan(profile):
    url = config.env("EMBER_ENGINE_URL")
    address = profile.get("address") or ""
    if profile.get("lat") is not None and profile.get("lon") is not None and not address:
        address = f'{profile["lat"]},{profile["lon"]}'
    if url:
        try:
            r = httpx.post(url.rstrip("/") + "/plan",
                           json={"address": address, "profile": engine_input(profile), "client_id": profile["id"]},
                           timeout=30.0)
        except httpx.HTTPError as e:
            raise EngineError(f"Engine at {url} unreachable: {e}") from e
        if r.status_code != 200:
            raise EngineError(f"Engine error {r.status_code}: {r.text[:300]}")
        return r.json()
    try:
        return coreplan.make_plan(bundle(), address, engine_input(profile), client_id=profile["id"])
    except coreplan.PlanError as e:
        raise EngineError(str(e)) from e
