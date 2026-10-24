"""Offline test helpers: every network call (Apify actors, Claude, Nominatim, FRAP) is faked."""

from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text())


LONG_QUOTE = (
    "Nurses and patients waited out the flames in the Walgreens parking lot on Clark Road, said Maria Gonzalez, "
    "a nurse, adding that the asphalt and the low curbs around the lot kept the fire away from the cars while embers "
    "rained down for hours and the smoke turned day into night over the whole ridge and beyond it."
)

CANNED = {
    "ARTICLE-KMART": [
        {"place": "Kmart parking lot on Clark Road", "kind": "parking lot", "people_count_hint": 50,
         "quote": "Joe Kennedy said he and about 50 others sheltered in the Kmart parking lot on Clark Road."},
        {"place": "Lake Concow", "kind": "lake", "quote": "Mrs. Lopez drove to Lake Concow and waited in the water."},
        {"place": "Sacramento Convention Center", "kind": "building",
         "quote": "Others were evacuated to the Sacramento Convention Center days later."},
        {"place": "Joe Kennedy's house", "kind": "building", "quote": "Joe Kennedy stayed at Joe Kennedy's house."},
    ],
    "ARTICLE-WALGREENS": [
        {"place": "Walgreens parking lot on Clark Road", "kind": "parking lot", "quote": LONG_QUOTE},
    ],
    "REDDIT-KMART": [
        {"place": "Kmart lot in Paradise", "kind": "parking_lot_typo",
         "quote": "My family made it to the Kmart lot in Paradise and stayed there until the fire passed."},
    ],
}


class FakeMessages:
    def __init__(self, canned: dict[str, list] | None = None, fail_marker: str | None = None):
        self.canned = canned if canned is not None else CANNED
        self.fail_marker = fail_marker
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        content = kwargs["messages"][0]["content"]
        if self.fail_marker and self.fail_marker in content:
            raise RuntimeError("simulated API error")
        places = next((v for k, v in self.canned.items() if k in content), [])
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps({"places": places}))],
        )


class FakeAnthropic:
    def __init__(self, **kw: Any):
        self.messages = FakeMessages(**kw)


class FakeApify:
    """Stands in for Actor.call + dataset fetch. Records every (actor_id, input)."""

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, actor_id: str, run_input: dict) -> list[dict]:
        self.calls.append((actor_id, run_input))
        if any(f in actor_id for f in self.fail):
            raise RuntimeError(f"{actor_id} run finished with status FAILED")
        if "google-search-scraper" in actor_id:
            return load("google_serp.json")
        if "website-content-crawler" in actor_id:
            return load("crawler_pages.json")
        if "reddit-scraper-lite" in actor_id:
            return load("reddit_posts.json")
        raise AssertionError(actor_id)


def make_transport(frap: Any = "default", nifc: Any = None, nominatim: dict | None = None, log: list | None = None):
    """httpx.MockTransport for FRAP / NIFC / Nominatim."""
    frap = load("frap_camp.json") if frap == "default" else frap
    nominatim = load("nominatim.json") if nominatim is None else nominatim

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        url = str(request.url)
        q = parse_qs(urlparse(url).query)
        if "California_Historic_Fire_Perimeters" in url:
            if isinstance(frap, int):
                return httpx.Response(frap)
            return httpx.Response(200, json=frap if "CAMP" in q["where"][0] else {"features": []})
        if "InterAgencyFirePerimeterHistory" in url:
            if nifc is None:
                return httpx.Response(200, json={"features": []})
            return httpx.Response(200, json=nifc)
        if "nominatim" in url:
            return httpx.Response(200, json=nominatim.get(q["q"][0].lower(), []))
        raise AssertionError(f"unexpected request {url}")

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_anthropic() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture
def fake_apify() -> FakeApify:
    return FakeApify()
