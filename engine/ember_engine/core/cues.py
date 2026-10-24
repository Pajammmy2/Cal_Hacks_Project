"""Turn cues from a route, using only the fixed templates in shared/turn_templates.json.

Every string produced here is pre-generable for Cartesia. Navigator/EmberCore/Cues.swift ports this file exactly.
"""
from . import geo, shared

SLOPE_MIN_PCT = 4.0
SLOPE_MIN_LEN_M = 30.0


def round_meters(m):
    return int(min(500, max(10, round(m / 10.0) * 10)))


def display_name(edge):
    t = shared.templates()
    if edge.get("name"):
        return edge["name"]
    if edge.get("road_class") in t["path_classes"]:
        return t["unnamed_path"]
    return t["unnamed_street"]


def fill(template_key, **vars_):
    text = shared.templates()[template_key].format(**vars_)
    return {"template": template_key, "vars": {k: v for k, v in vars_.items()}, "text": text}


def legs(graph, route):
    """Group consecutive route edges with the same display name."""
    out = []
    for i, (ei, fwd) in enumerate(zip(route["edges"], route["forward"])):
        e = graph.edges[ei]
        name = display_name(e)
        a, b = route["nodes"][i], route["nodes"][i + 1]
        if out and out[-1]["street"] == name:
            leg = out[-1]
        else:
            leg = {"street": name, "edges": [], "fwd": [], "nodes": [a], "length_m": 0.0, "rise_m": 0.0}
            out.append(leg)
        leg["edges"].append(ei)
        leg["fwd"].append(fwd)
        leg["nodes"].append(b)
        leg["length_m"] += e["length_m"]
        grade = e["grade_pct"] if fwd else -e["grade_pct"]
        leg["rise_m"] += grade / 100.0 * e["length_m"]
    for leg in out:
        leg["blocks"] = max(1, sum(1 for n in leg["nodes"][1:] if graph.degree[n] >= 3))
    return out


def build_cues(graph, route, refuge_name):
    t = shared.templates()
    cues = []
    if not route["edges"]:
        c = fill("arrive", refuge=refuge_name)
        c.update(distance_m=0.0, node=route["nodes"][0])
        return [c]
    dist = 0.0
    lg = legs(graph, route)
    for li, leg in enumerate(lg):
        start_node = leg["nodes"][0]
        if li == 0:
            b = graph.edge_bearing(leg["edges"][0], leg["fwd"][0])
            c = fill("start", street=leg["street"], direction=geo.direction_word(b, t["directions"]))
        else:
            prev = lg[li - 1]
            b_in = graph.edge_bearing(prev["edges"][-1], prev["fwd"][-1])
            b_out = graph.edge_bearing(leg["edges"][0], leg["fwd"][0])
            d = geo.signed_turn(b_in, b_out)
            side = "right" if d > 0 else "left"
            ad = abs(d)
            if ad < 30:
                c = fill("continue", street=leg["street"])
            elif ad < 60:
                c = fill("turn_slight", side=side, street=leg["street"])
            elif ad < 150:
                c = fill("turn", side=side, street=leg["street"])
            else:
                c = fill("turn_sharp", side=side, street=leg["street"])
        c.update(distance_m=round(dist, 1), node=start_node)
        cues.append(c)
        if leg["blocks"] >= 2:
            k = fill("keep_blocks", street=leg["street"], n=leg["blocks"])
        else:
            k = fill("keep_meters", street=leg["street"], n=round_meters(leg["length_m"]))
        k.update(distance_m=round(dist, 1), node=start_node)
        cues.append(k)
        avg = abs(leg["rise_m"]) / leg["length_m"] * 100.0 if leg["length_m"] > 0 else 0.0
        if leg["length_m"] >= SLOPE_MIN_LEN_M and avg >= SLOPE_MIN_PCT:
            s = fill("downhill" if leg["rise_m"] < 0 else "uphill", n=round_meters(leg["length_m"]))
            s.update(distance_m=round(dist, 1), node=start_node)
            cues.append(s)
        dist += leg["length_m"]
    c = fill("arrive", refuge=refuge_name)
    c.update(distance_m=round(dist, 1), node=route["nodes"][-1])
    cues.append(c)
    return cues


def _merge_keep(turn_text, keep):
    if keep["template"] == "keep_blocks":
        n = keep["vars"]["n"]
        return f"{turn_text} Keep going for {n} blocks."
    return f"{turn_text} Keep going for {keep['vars']['n']} meters."


def card_steps(cues, max_steps=7):
    """4-7 plain steps for the printed card: drop slope cues, fold each keep cue into its turn."""
    steps = []  # list of (text, length_weight)
    i = 0
    core = [c for c in cues if c["template"] not in ("downhill", "uphill")]
    while i < len(core):
        c = core[i]
        nxt = core[i + 1] if i + 1 < len(core) else None
        if c["template"] != "arrive" and nxt is not None and nxt["template"] in ("keep_blocks", "keep_meters"):
            steps.append([_merge_keep(c["text"], nxt), nxt["vars"]["n"] if nxt["template"] == "keep_meters" else nxt["vars"]["n"] * 100])
            i += 2
        else:
            steps.append([c["text"], 10 ** 9 if c["template"] == "arrive" else 0])
            i += 1
    # merge the shortest adjacent pair (never the final arrive step) until we fit
    while len(steps) > max_steps:
        best_j, best_w = None, None
        for j in range(1, len(steps) - 1):
            w = steps[j - 1][1] + steps[j][1]
            if best_w is None or w < best_w:
                best_j, best_w = j, w
        a, b = steps[best_j - 1], steps[best_j]
        steps[best_j - 1] = [a[0] + " " + b[0], a[1] + b[1]]
        del steps[best_j]
    return [s[0] for s in steps]


def all_cue_texts_for_streets(streets, refuge_names):
    """Every turn template instantiated with these street names (for Cartesia pre-generation after a replan)."""
    t = shared.templates()
    out = set()
    for s in streets:
        out.add(t["continue"].format(street=s))
        for side in ("left", "right"):
            for key in ("turn_slight", "turn", "turn_sharp"):
                out.add(t[key].format(side=side, street=s))
        for d in t["directions"]:
            out.add(t["start"].format(street=s, direction=d))
    for r in refuge_names:
        out.add(t["arrive"].format(refuge=r))
        out.add(t["arrived"].format(refuge=r))
        out.add(t["arrived_building"].format(refuge=r))
    return out
