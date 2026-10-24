"""Engine HTTP API for the staff tool (spec "Engine call (POST /plan)"). Binds 127.0.0.1 by default.

    python engine/serve.py [--host 127.0.0.1] [--port 8765] [--bundles bundles/]

POST /plan {county, address, profile, blocked?: [edge index], client_id?} -> plan JSON (CONTRACTS.md "Plan JSON")
GET  /bundles/{county}/manifest
GET  /healthz
"""
import argparse
import os
import re
import sys
import threading
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from ember_engine.core import plan as planmod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = Path(os.environ.get("EMBER_BUNDLES", ROOT / "bundles"))
_COUNTY = re.compile(r"^[a-z0-9_-]{1,64}$")


class PlanRequest(BaseModel):
    county: str
    address: Optional[str] = None
    profile: dict
    blocked: Optional[List[int]] = None
    client_id: Optional[str] = None


app = FastAPI(title="Ember engine", version="1")
_cache = {}
_lock = threading.Lock()


def bundle_dir(county):
    if not _COUNTY.match(county or ""):
        raise HTTPException(400, "county must be a lowercase bundle name")
    d = BUNDLES / county
    if not (d / "graph.json").exists() or not (d / "refuges.json").exists():
        raise HTTPException(404, f"no bundle for county {county!r}")
    return d


def get_bundle(county):
    """One loaded Bundle per county, reloaded when refuges.json or graph.json changes on disk."""
    d = bundle_dir(county)
    stamp = max((d / "graph.json").stat().st_mtime, (d / "refuges.json").stat().st_mtime)
    with _lock:
        hit = _cache.get(county)
        if hit is None or hit[0] != stamp:
            hit = (stamp, planmod.Bundle(d))
            _cache[county] = hit
        return hit[1]


@app.get("/healthz")
def healthz():
    return {"ok": True, "bundles": sorted(p.name for p in BUNDLES.iterdir() if (p / "manifest.json").exists())
            if BUNDLES.exists() else []}


@app.get("/bundles/{county}/manifest")
def manifest(county: str):
    return get_bundle(county).manifest


@app.post("/plan")
def plan(req: PlanRequest):
    b = get_bundle(req.county)
    blocked = frozenset(req.blocked or ())
    n_edges = len(b.graph.edges)
    if any(i < 0 or i >= n_edges for i in blocked):
        raise HTTPException(422, f"blocked edge index out of range 0..{n_edges - 1}")
    try:
        return planmod.make_plan(b, req.address or "", req.profile, blocked=blocked, client_id=req.client_id)
    except planmod.PlanError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:          # unknown mobility etc.
        raise HTTPException(422, str(e))


def main(argv=None):
    global BUNDLES
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bundles", default=str(BUNDLES))
    a = ap.parse_args(argv)
    BUNDLES = Path(a.bundles)
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
