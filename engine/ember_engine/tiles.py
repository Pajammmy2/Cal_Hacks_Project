"""Offline vector tiles (tiles.mbtiles) for the bbox: graph edges, buildings, refuge polygons, z12-16 via tippecanoe.

Without tippecanoe a valid but empty MBTiles (metadata only) is written and the limitation is returned.
"""
import json
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from shapely.geometry import mapping

MINZOOM, MAXZOOM = 12, 16


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def layers(graph, buildings, refuges):
    nodes = graph["nodes"]
    edges = [{"type": "Feature", "properties": {"name": e["name"], "road_class": e["road_class"],
                                                "steps": e["steps"], "surface": e["surface"]},
              "geometry": {"type": "LineString", "coordinates": [[nodes[e["a"]]["lon"], nodes[e["a"]]["lat"]],
                                                                 [nodes[e["b"]]["lon"], nodes[e["b"]]["lat"]]]}}
             for e in graph["edges"]]
    blds = [{"type": "Feature", "properties": {"building": t.get("building")}, "geometry": mapping(g)}
            for t, g in buildings]
    refs = [{"type": "Feature", "properties": {"id": r["id"], "name": r["name"], "kind": r["kind"], "score": r["score"]},
             "geometry": {"type": "Polygon", "coordinates": [r["polygon"]]}} for r in refuges]
    return {"edges": _fc(edges), "buildings": _fc(blds), "refuges": _fc(refs)}


def empty_mbtiles(path, name, bbox):
    path = Path(path)
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE metadata (name TEXT, value TEXT);"
                     "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
                     "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);")
    w, s, e, n = bbox
    db.executemany("INSERT INTO metadata VALUES (?,?)", [
        ("name", name), ("format", "pbf"), ("bounds", f"{w},{s},{e},{n}"),
        ("center", f"{(w + e) / 2},{(s + n) / 2},{MINZOOM}"), ("minzoom", str(MINZOOM)), ("maxzoom", str(MAXZOOM)),
        ("type", "overlay"), ("description", "EMPTY: tippecanoe not available at build time"),
        ("json", json.dumps({"vector_layers": []}))])
    db.commit()
    db.close()


def build(path, name, bbox, graph, buildings, refuges):
    """Returns (source description, limitation or None)."""
    exe = shutil.which("tippecanoe")
    if not exe:
        empty_mbtiles(path, name, bbox)
        return "empty-mbtiles", "tippecanoe not installed; tiles.mbtiles has metadata only"
    w, s, e, n = bbox
    with tempfile.TemporaryDirectory() as td:
        args = [exe, "-o", str(path), "--force", "-Z", str(MINZOOM), "-z", str(MAXZOOM), "-n", name,
                f"--clip-bounding-box={w},{s},{e},{n}", "--drop-densest-as-needed", "--quiet"]
        for lname, fc in layers(graph, buildings, refuges).items():
            p = Path(td) / f"{lname}.geojson"
            p.write_text(json.dumps(fc))
            args += ["-L", f"{lname}:{p}"]
        subprocess.run(args, check=True)
    ver = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return f"tippecanoe {(ver.stderr or ver.stdout).strip()} z{MINZOOM}-{MAXZOOM}", None
