# Reviewed extra refuge candidates

OpenStreetMap is missing some places that matter. In Paradise, the Walgreens parking lot is mapped only as a point,
so the engine cannot score it. Add such places here as polygons, and they go through exactly the same scoring as OSM
features. This file can add a place, but it can never set or raise a score.

1. Open https://geojson.io, zoom to the place, and switch to satellite view.
2. Trace the paved lot (or field or building) with the polygon tool.
3. Give the polygon OSM-style properties: `amenity: parking` for a lot (or `leisure`, `landuse`, or `building` +
   `building:material`), an optional `name`, and **`reviewed_by`** (required; the build refuses features without it).
   `source` and `note` are kept out of the tags.
4. Save as `<county>.geojson` in this folder, then rebuild:

```bash
.venv/bin/python engine/build_bundle.py --county paradise --bbox -121.70,39.70,-121.45,39.86 \
    --fuel-version LF2016 --extra-candidates engine/extra_candidates/paradise.geojson
.venv/bin/python engine/validate.py --county paradise
```

The better long-term fix is to map the place in OpenStreetMap itself, so everyone benefits.
