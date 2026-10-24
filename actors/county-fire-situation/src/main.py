"""county-fire-situation: one snapshot of a California county's fire situation.

Input  {county: string, state: "CA"}
Output {county, fetched_at, incidents, closures, zones, outages, errors} pushed as one dataset item
and stored as OUTPUT in the key-value store. Schedule it every 15 minutes during an incident.
"""

from __future__ import annotations

from typing import Any

from .common import counties, resolve_county
from .situation import build_situation


class InputError(ValueError):
    pass


def parse_input(raw: dict[str, Any] | None) -> str:
    raw = raw or {}
    state = raw.get("state", "CA")
    if str(state).strip().upper() != "CA":
        raise InputError('state must be "CA" (only California is supported)')
    name = raw.get("county")
    if not isinstance(name, str) or not name.strip():
        raise InputError('county (string) is required, e.g. "Butte"')
    county = resolve_county(name)
    if county is None:
        raise InputError(f"unknown California county {name!r}; expected one of: {', '.join(counties())}")
    return county


async def main() -> None:
    from apify import Actor

    async with Actor:
        try:
            county = parse_input(await Actor.get_input())
        except InputError as exc:
            await Actor.fail(status_message=f"Invalid input: {exc}")
            return
        situation = await build_situation(county)
        await Actor.push_data(situation)
        await Actor.set_value("OUTPUT", situation)
        errs = [e["source"] for e in situation["errors"] if e["level"] == "error"]
        await Actor.set_status_message(
            f"{county}: {len(situation['incidents'])} incidents, {len(situation['closures'])} closures, "
            f"{len(situation['zones'])} zones, {len(situation['outages'])} outages"
            + (f"; failed sources: {', '.join(errs)}" if errs else ""),
            is_terminal=True,
        )
