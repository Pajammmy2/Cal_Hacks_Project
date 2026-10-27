"""The plan must start at the client's own address: the first cue names the address street. Owner bug: Harold's card
said 5974 Pentz Road but step 1 was Canyon View Drive (his registry row had no lat/lon and the geocoder settled on the
nearest house number on another street). Clients whose address could only be matched to a neighbour are reported, not
silently accepted."""
import json, os, re
from pathlib import Path
import pytest
from ember_staff import db

SUFFIX = {"rd": "road", "dr": "drive", "ln": "lane", "st": "street", "ave": "avenue", "ct": "court", "blvd": "boulevard"}


def street_core(address):
    first = (address or "").split(",")[0]
    m = re.match(r"^\s*\d+\s+(.+?)\s*$", first)
    words = [SUFFIX.get(w.rstrip(".").lower(), w.lower()) for w in (m.group(1) if m else first).split()]
    return " ".join(words[:-1]) if len(words) > 1 else (words[0] if words else "")


def check(plan, address, cid):
    if not plan.get("choices"):
        return                                     # shelter-in-place plan has no route
    cue = plan["choices"][0]["cues"][0]["text"].lower()
    core = street_core(address)
    assert core and (core in cue or cue.startswith(("walk", "roll", "go to"))), \
        f"{cid}: first cue {cue!r} does not start on {address!r} (geocode={plan.get('origin', {}).get('geocode')})"


# The fixture bundle is a synthetic grid whose address points do not lie on their named streets, so the check runs
# on the real Paradise plans (the six demo clients) whenever they are present.


REAL = Path(os.environ.get("EMBER_REAL_PLANS", "/Users/devin/work/deliverables/bundle_six/plans"))
PLANS = sorted(REAL.glob("c_*.json")) if REAL.is_dir() else []
REG = Path(__file__).resolve().parents[1] / "sample_registry_paradise.csv"


@pytest.mark.skipif(not PLANS, reason="real Paradise plans not present")
@pytest.mark.parametrize("plan_path", [str(p) for p in PLANS])
def test_real_paradise_plans_start_at_home(plan_path):
    import csv
    addr = {r["id"]: r["address"] for r in csv.DictReader(REG.open())}
    plan = json.loads(Path(plan_path).read_text())
    check(plan, addr[plan["client_id"]], plan["client_id"])
