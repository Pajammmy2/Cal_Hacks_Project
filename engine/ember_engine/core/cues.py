import re
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
    out = _merge_pingpong(out, shared.templates())
    for leg in out:
        leg["blocks"] = max(1, sum(1 for n in leg["nodes"][1:] if graph.degree[n] >= 3))
    return out


PINGPONG_MAX_M = 120.0


def _merge_pingpong(legs_, t):
    """A short unnamed leg between two legs of the same named street (OSM sidewalks and service stubs beside a
    road) is the same street to a person: fold it in, so the cues do not say "the side road, then Skyway, then the
    side road". Ported exactly by Cues.swift."""
    unnamed = (t["unnamed_street"], t["unnamed_path"])
    i = 1
    while i < len(legs_) - 1:
        mid, prev, nxt = legs_[i], legs_[i - 1], legs_[i + 1]
        if mid["street"] in unnamed and mid["length_m"] < PINGPONG_MAX_M and prev["street"] == nxt["street"] \
                and prev["street"] not in unnamed:
            for leg in (mid, nxt):
                prev["edges"] += leg["edges"]
                prev["fwd"] += leg["fwd"]
                prev["nodes"] += leg["nodes"][1:]
                prev["length_m"] += leg["length_m"]
                prev["rise_m"] += leg["rise_m"]
            del legs_[i:i + 2]
        else:
            i += 1
    return legs_


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


CARD_MAX_WORDS = 90      # per route; two refuges + notes must fit a two-page card even for 30-cue OSM routes
CARD_MIN_STEPS = 4
CHAIN_HOP_M = 200        # turns closer than this read as one move: "Turn left onto Gate Lane, then Cabernet Lane."
_ONTO = re.compile(r"^(?:Turn (?:slight |sharp )?(?:left|right)|Continue) onto (.+?)\.?$")


def _segments(cues):
    """[{turn, keep_text, keep_m, arrive}] with each keep cue folded into the turn before it; slope cues dropped."""
    segs = []
    core = [c for c in cues if c["template"] not in ("downhill", "uphill")]
    i = 0
    while i < len(core):
        c = core[i]
        nxt = core[i + 1] if i + 1 < len(core) else None
        seg = {"turn": c["text"], "keep_text": None, "keep_m": 0, "arrive": c["template"] == "arrive"}
        if not seg["arrive"] and nxt is not None and nxt["template"] in ("keep_blocks", "keep_meters"):
            seg["keep_text"] = _merge_keep("", nxt).strip()
            seg["keep_m"] = nxt["vars"]["n"] if nxt["template"] == "keep_meters" else nxt["vars"]["n"] * 100
            i += 1
        segs.append(seg)
        i += 1
    return segs


def _weight(step):
    return 10 ** 9 if step[-1]["arrive"] else sum(s["keep_m"] for s in step)


def _render(step, compact):
    if not compact:
        return " ".join(s["turn"] + (" " + s["keep_text"] if s["keep_text"] else "") for s in step)
    out, chain, prev, head_onto = [], None, None, False
    for s in step:
        m = _ONTO.match(s["turn"]) if prev is not None else None
        if m and head_onto and prev["keep_m"] < CHAIN_HOP_M:
            chain.append(m.group(1))                     # short hop: drop its keep, name the next street
        else:
            if chain is not None:
                out.append(_flush(chain, prev))
            chain = [s["turn"].rstrip(".")]
            head_onto = _ONTO.match(s["turn"]) is not None   # never chain onto the start or arrive sentence
        prev = s
    out.append(_flush(chain, prev))
    return " ".join(out)


def _flush(chain, last):
    text = chain[0] + "".join(f", then {st}" for st in chain[1:]) + "."
    if last["keep_text"] and (last["keep_m"] >= CHAIN_HOP_M or len(chain) == 1):
        text += " " + last["keep_text"]
    return text


def _words(steps, compact):
    return sum(len(_render(st, compact).split()) for st in steps)


def _merge_shortest(steps):
    best_j, best_w = None, None
    for j in range(1, len(steps) - 1):
        w = _weight(steps[j - 1]) + _weight(steps[j])
        if best_w is None or w < best_w:
            best_j, best_w = j, w
    steps[best_j - 1] = steps[best_j - 1] + steps[best_j]
    del steps[best_j]


def card_steps(cues, max_steps=7, max_words=CARD_MAX_WORDS):
    """4-7 plain steps for the printed card: drop slope cues, fold each keep cue into its turn, merge the shortest
    hops first. Long OSM routes (30+ cues) are also held to a word budget so the card stays on two pages: a merged
    step then chains its short hops ("Turn left onto Gate Lane, then Cabernet Lane, then Clark Road.") and, if
    still too long, keeps merging down to 4 steps. The first (start) and last (arrive) sentences never change."""
    steps = [[seg] for seg in _segments(cues)]
    while len(steps) > max_steps:
        _merge_shortest(steps)
    compact = False
    if max_words and _words(steps, False) > max_words:
        compact = True
        while _words(steps, True) > max_words and len(steps) > CARD_MIN_STEPS:
            _merge_shortest(steps)
    return [_render(st, compact) for st in steps]


SAME_WAY_MIN_CUES = 4   # start + keep + one more turn + keep: otherwise just print B in full


def card_steps_after(cues_a, cues_b, which="A"):
    """Card steps for route B when it leaves home the same way as A: the shared part becomes one line
    ("Same way as A until Skyway.") and the rest is stepped as usual. Printed only, never spoken."""
    n = 0
    while n < min(len(cues_a), len(cues_b)) and cues_a[n]["template"] == cues_b[n]["template"] \
            and cues_a[n]["text"] == cues_b[n]["text"] and cues_a[n].get("node") == cues_b[n].get("node"):
        n += 1
    while n > 0 and cues_b[n - 1]["template"] in ("keep_blocks", "keep_meters", "downhill", "uphill") is False:
        break
    if n < SAME_WAY_MIN_CUES or n >= len(cues_b) - 1:
        return card_steps(cues_b)
    # end the shared part on a whole leg: back up to the last turn cue that both share
    while n > 0 and cues_b[n - 1]["template"] in ("downhill", "uphill"):
        n -= 1
    street = None
    for c in reversed(cues_b[:n]):
        if c["template"] in ("keep_blocks", "keep_meters"):
            street = c["vars"].get("street")
            break
    if not street:
        return card_steps(cues_b)
    first = fill("same_way", which=which, street=street)
    return card_steps([first] + cues_b[n:], max_steps=7)


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
