"""CAL FIRE active incidents: the JSON behind https://www.fire.ca.gov/incidents.

Endpoint: https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false
(the www.fire.ca.gov host returns Akamai "Access Denied" to non-browser clients; the incidents.
subdomain serves the same API). `County` can list several counties ("Butte, Plumas").
"""

from __future__ import annotations

from typing import Any

import httpx

from .common import USER_AGENT, iso_utc, to_float, url


def normalize(it: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": it.get("UniqueId"),
        "name": (it.get("Name") or "").strip(),
        "type": it.get("Type"),
        "lat": to_float(it.get("Latitude")),
        "lon": to_float(it.get("Longitude")),
        "acres": to_float(it.get("AcresBurned")),
        "containment": to_float(it.get("PercentContained")),
        "updated": iso_utc(it.get("Updated")),
        "started": iso_utc(it.get("Started")),
        "location": it.get("Location"),
        "admin_unit": it.get("AdminUnit"),
        "url": it.get("Url"),
    }


def in_county(it: dict[str, Any], county: str) -> bool:
    names = [c.strip().lower() for c in str(it.get("County") or "").replace(";", ",").split(",")]
    return county.lower() in names


async def fetch_incidents(client: httpx.AsyncClient, county: str) -> tuple[list, list]:
    r = await client.get(url("EMBER_CALFIRE_URL"), timeout=30,
                         headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list, got {type(data).__name__}")
    items = [normalize(it) for it in data
             if in_county(it, county) and it.get("IsActive", True) and not it.get("Final", False)]
    items.sort(key=lambda x: -(x["acres"] or 0))
    return items, []
