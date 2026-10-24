"""Dump router + cue + hashing outputs on bundles/fake for the Swift parity test (navigator/Tests/EmberCoreTests).

    .venv/bin/python engine/tests/parity/dump_parity.py   ->  engine/tests/parity/fake_parity.json
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "engine"))

from ember_engine.core import cues, geo, hashing, plan, router, shared  # noqa: E402

FAKE = ROOT / "bundles" / "fake"
OUT = Path(__file__).resolve().parent / "fake_parity.json"

PROFILES = [("manual_chair", 100.0), ("manual_chair_pushed", 100.0), ("power_chair", 100.0),
            ("power_chair", 6.0), ("walker", 100.0), ("bedbound", 100.0)]


def main():
    b = plan.Bundle(FAKE)
    g, refuges = b.graph, b.refuges
    rng = random.Random(20261023)
    origins = sorted(rng.sample(range(len(g.nodes)), 20))
    hist = b.perimeters["historical"][1]["polygon"]
    scenarios = [
        {"name": "none", "fire_bearing": None, "perimeter": None, "blocked": []},
        {"name": "wind", "fire_bearing": float(b.wind["direction_from_deg"]), "perimeter": None, "blocked": []},
        {"name": "perimeter", "fire_bearing": 200.0, "perimeter": hist, "blocked": []},
    ]
    cases = []
    for o in origins:
        for key, batt in PROFILES:
            prof = router.Profile(key, batt)
            for sc in scenarios:
                blocked = set(sc["blocked"])
                res = router.choose(g, refuges, prof, o, sc["fire_bearing"], sc["perimeter"], frozenset(blocked))
                case = {"origin": o, "profile": key, "battery_pct": batt, "scenario": sc["name"],
                        "fire_bearing": sc["fire_bearing"], "perimeter": sc["perimeter"], "blocked": sorted(blocked),
                        "choices": [_choice(g, c) for c in res]}
                cases.append(case)
                # blocked re-plan: block the first edge of A and route again
                if sc["name"] == "wind" and res and res[0]["route"]["edges"]:
                    blocked2 = sorted({res[0]["route"]["edges"][0]})
                    res2 = router.choose(g, refuges, prof, o, sc["fire_bearing"], None, frozenset(blocked2))
                    cases.append({"origin": o, "profile": key, "battery_pct": batt, "scenario": "wind_blocked",
                                  "fire_bearing": sc["fire_bearing"], "perimeter": None, "blocked": blocked2,
                                  "choices": [_choice(g, c) for c in res2]})

    snaps = []
    lat0, lon0 = min(g.lat), min(g.lon)
    for _ in range(40):
        lat = lat0 + rng.uniform(-0.002, 0.015)
        lon = lon0 + rng.uniform(-0.002, 0.019)
        for key in ("manual_chair", "walker"):
            n, d = g.snap(lat, lon, router.usable_origin(g, router.Profile(key)))
            snaps.append({"lat": lat, "lon": lon, "profile": key, "node": n, "d": d})

    texts = ["Say again?", "  Turn left  onto\tClark Rd.\n", "Keep going on Skyway for 4 blocks.",
             "Arrive at Lake Concow.", "Start on Pentz Rd. Go northeast.", "Downhill for 120 meters.",
             "Café été — Oroville Dr", "Blocking Clark Rd at Pearson Rd. Say yes to reroute."]
    for k in shared.phrases()["fixed"]:
        texts.append(k)
    hashes = [{"text": t, "normalized": hashing.normalize(t), "key": hashing.clip_key(t),
               "cartesia": hashing.for_cartesia(t)} for t in texts]

    geo_cases = []
    for _ in range(60):
        a = [rng.uniform(39.7, 39.8), rng.uniform(-121.7, -121.6), rng.uniform(39.7, 39.8), rng.uniform(-121.7, -121.6)]
        geo_cases.append({"p": a, "haversine": geo.haversine_m(*a), "bearing": geo.bearing_deg(*a)})
    turns = []
    for _ in range(60):
        x, y = rng.uniform(0, 360), rng.uniform(0, 360)
        turns.append({"a": x, "b": y, "angdiff": geo.angdiff(x, y), "signed": geo.signed_turn(x, y),
                      "word": geo.direction_word(x, shared.templates()["directions"])})

    OUT.write_text(json.dumps({"bundle": "fake", "cases": cases, "snaps": snaps, "hashes": hashes,
                               "geo": geo_cases, "turns": turns}, ensure_ascii=False))
    print(OUT, len(cases), "cases")


def _choice(g, c):
    r = c["route"]
    cl = cues.build_cues(g, r, c["refuge"]["name"])
    return {"refuge_id": c["refuge"]["id"], "score": c["refuge"]["score"],
            "route": {k: r[k] for k in ("nodes", "edges", "forward", "length_m", "time_s", "minutes")},
            "cues": [dict(x, key=hashing.clip_key(x["text"])) for x in cl],
            "card_steps": cues.card_steps(cl)}


if __name__ == "__main__":
    main()
