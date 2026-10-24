"""Live smoke test of every source fetcher (real network, no Apify platform, no keys).

Usage:  python scripts/smoke_live.py Butte
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.main import parse_input  # noqa: E402
from src.situation import build_situation  # noqa: E402


async def main(county_arg: str) -> None:
    county = parse_input({"county": county_arg, "state": "CA"})
    t0 = time.monotonic()
    s = await build_situation(county)
    print(f"{county}: fetched_at={s['fetched_at']} in {time.monotonic() - t0:.1f}s")
    for key in ("incidents", "closures", "zones", "outages"):
        print(f"  {key:9s} {len(s[key]):4d}  first: {json.dumps(s[key][0])[:200] if s[key] else '-'}")
    for e in s["errors"]:
        print(f"  [{e['level']}] {e['source']}: {e['message']}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Butte"))
