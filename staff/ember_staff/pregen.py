"""Cartesia pre-generation (spec: Cartesia track, pipeline steps 1-3). Runs after the card is stamped.

collect() gathers every string the navigator can say for this client; generate() synthesizes the missing ones into
bundles/<county>/audio/<sha1>.mp3 (+ index.json), or audio/clients/<client_id>/ for a cloned voice, then re-zips.
"""
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from . import cartesia, config, db, engine_client, plan_writer
from ember_engine.core import cues as cuemod
from ember_engine.core import hashing, router, shared

CONCURRENCY = 4
MAX_REPLAN_EDGES = 400
CARTESIA_LANGS = {"en", "es", "fr", "de", "pt", "zh", "ja", "hi", "it", "ko", "nl", "pl", "ru", "sv", "tr"}
DEVICE_SPOKEN = {"oxygen": "Oxygen", "ventilator": "Ventilator", "power_chair": "Power chair", "cpap": "CPAP"}
_running = set()
_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- step 1: collect

def _streets_of(cue_list):
    return [c["vars"]["street"] for c in cue_list if "street" in (c.get("vars") or {})]


def replans(profile, plan, bundle, which=(0, 1), selected=None):
    """Cue lists the core produces after blocking each edge of route A (and B) once, re-planned from the origin
    and from the node where the blocked edge starts (where the navigator would be when the user says "blocked")."""
    out = []
    if bundle is None or not plan or not plan.get("choices"):
        return out
    keys = [shared.profile_key_for(profile)]
    if keys[0] == "manual_chair":
        keys.append("manual_chair_pushed")   # caregiver mode on the phone
    sel = selected or [0, 1]
    origin = plan["origin"]["node"]
    for key in keys:
        prof = router.Profile(key, shared.battery_pct_for(profile))
        for w in which:
            if w >= len(sel) or sel[w] is None or sel[w] >= len(plan["choices"]):
                continue
            route = plan["choices"][sel[w]]["route"]
            for i, ei in enumerate(route["edges"][:MAX_REPLAN_EDGES]):
                for start in {origin, route["nodes"][i]}:
                    for c in router.choose(bundle.graph, bundle.refuges, prof, start, plan.get("fire_bearing_deg"),
                                           None, frozenset({ei})):
                        out.append((c["refuge"]["name"], c["route"]["minutes"],
                                    cuemod.build_cues(bundle.graph, c["route"], c["refuge"]["name"])))
    return out


def _pushed_choices(profile, plan, bundle):
    if bundle is None or not plan or shared.profile_key_for(profile) != "manual_chair":
        return []
    prof = router.Profile("manual_chair_pushed")
    out = []
    for c in router.choose(bundle.graph, bundle.refuges, prof, plan["origin"]["node"], plan.get("fire_bearing_deg"), None):
        out.append((c["refuge"]["name"], c["route"]["minutes"], cuemod.build_cues(bundle.graph, c["route"], c["refuge"]["name"])))
    return out


def cross_pairs(bundle, node_lists):
    """(street, cross_street) pairs meeting at intersections along the routes."""
    pairs = set()
    if bundle is None:
        return pairs
    g = bundle.graph
    for nodes in node_lists:
        for n in nodes:
            names = {cuemod.display_name(g.edges[ei]) for ei, _, _ in g.adj[n]}
            for a in names:
                for b in names:
                    if a != b:
                        pairs.add((a, b))
    return pairs


def collect(row, bundle="auto", include_replans=True):
    """{text: language} for every string the navigator can say for this client."""
    profile, plan, text = row["profile"], row.get("plan") or {}, row.get("text") or {}
    if bundle == "auto":
        try:
            bundle = engine_client.bundle(plan.get("county"))
        except Exception:
            bundle = None
    P = shared.phrases()
    T = shared.templates()
    out = {}

    def add(s, lang="en"):
        if s and s.strip():
            out.setdefault(hashing.normalize(s), lang)

    a, b = plan_writer.chosen(plan, row.get("selected"))
    routes = []   # (refuge name, minutes, cues)
    for c in plan.get("choices") or []:
        routes.append((c["refuge"]["name"], c["route"]["minutes"], c["cues"]))
    routes += _pushed_choices(profile, plan, bundle)
    if include_replans:
        routes += replans(profile, plan, bundle, selected=row.get("selected"))

    streets, refuges = [], []
    for name, _, cl in routes:
        for c in cl:
            add(c["text"])
        for s in _streets_of(cl):
            if s not in streets:
                streets.append(s)
        if name not in refuges:
            refuges.append(name)

    # every turn template with the streets and refuges on both routes (and their re-plans)
    for s in sorted(cuemod.all_cue_texts_for_streets(streets, refuges)):
        add(s)

    # card steps, shelter steps, device sentences (engine text and the reviewed card text)
    for c in (a, b):
        for s in (c or {}).get("card_steps", []):
            add(s)
    for s in (plan.get("shelter") or {}).get("steps", []):
        add(s)
    for d in plan.get("devices") or []:
        add(d.get("sentence"))
    lang = text.get("language")
    l2_code = lang if lang in CARTESIA_LANGS else None
    for k, arr in (text.get("sections") or {}).items():
        if k.endswith("_en"):
            for s in arr:
                add(s)
        elif k.endswith("_l2") and l2_code:
            for s in arr:
                add(s, l2_code)

    # fixed phrase set
    for s in P["fixed"]:
        add(s)
    tp = P["templates"]
    for d in T["directions"]:
        add(tp["fire_dir"].format(direction=d))
        add(tp["which_way"].format(direction=d))
    for s in streets:
        add(tp["blocking"].format(street=s))
        add(tp["where"].format(street=s))
    for s1, s2 in sorted(cross_pairs(bundle, [r["nodes"] for r in
                                             [c["route"] for c in (plan.get("choices") or [])]])):
        if s1 in streets:
            add(tp["blocking_cross"].format(street=s1, cross_street=s2))
    max_min = max([m for _, m, _ in routes] + [0])
    for n in range(1, min(500, max(60, max_min + 15)) + 1):
        add(tp["how_long"].format(n=n))
    for name, minutes, _ in routes:
        add(tp["choose"].format(refuge=name, n=minutes))
        add(tp["or_b"].format(refuge=name, n=minutes))
    dev_minutes = list(range(1, 121)) + list(range(130, 501, 10))
    for d in profile.get("devices") or []:
        lbl = DEVICE_SPOKEN.get(d.get("kind"))
        if lbl and d.get("kind") != "cpap":
            for n in dev_minutes:
                add(tp["leave_now_dev"].format(device=lbl, n=n))

    # fragments per street + numbers 1-500 as standalone strings
    for parts in P["fragments"].values():
        for frag in parts:
            if frag == "{n}":
                continue
            if "{street}" in frag:
                for s in streets:
                    add(frag.format(street=s))
            else:
                add(frag)
    for n in range(P["numbers"]["from"], P["numbers"]["to"] + 1):
        add(str(n))
    return out


def keys(strings):
    return {hashing.clip_key(s) for s in strings}


# ---------------------------------------------------------------- steps 2-3: synthesize

def audio_dir(row):
    county = (row.get("plan") or {}).get("county") or config.county()
    base = config.bundle_dir(county) / "audio"
    voice = row["profile"].get("voice") or {}
    if voice.get("kind") == "clone" and voice.get("voice_id"):
        return base / "clients" / row["id"], voice["voice_id"], None   # cloned voice: natural speed
    return base, config.env("CARTESIA_VOICE_ID"), cartesia.DEFAULT_SPEED


def _zip(county):
    path = config.ENGINE_DIR / "fixtures" / "make_fake_bundle.py"
    spec = importlib.util.spec_from_file_location("ember_make_fake_bundle", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.zip_bundle(config.bundle_dir(county))


def generate(row, tts=None, dry_run=False, progress=None):
    """Synthesize every missing clip. Returns a summary dict. dry_run: only report what would be generated."""
    strings = collect(row)
    out_dir, voice_id, speed = audio_dir(row)
    index_path = out_dir / "index.json"
    index = {}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text())
        except ValueError:
            index = {}
    todo = []
    for s, lang in strings.items():
        k = hashing.clip_key(s)
        if (out_dir / f"{k}.mp3").exists():
            index.setdefault(k, s)
        else:
            todo.append((k, s, lang))
    summary = {"total": len(strings), "existing": len(strings) - len(todo), "to_generate": len(todo),
               "generated": 0, "failed": 0, "dir": str(out_dir), "normalized": bool(cartesia.ffmpeg()),
               "errors": [], "model_note": None}
    if dry_run:
        summary["keys"] = sorted(keys(strings))
        return summary
    if not voice_id:
        raise cartesia.CartesiaError("No voice: set CARTESIA_VOICE_ID (default calm voice) or record a cloned voice.")
    out_dir.mkdir(parents=True, exist_ok=True)
    tts = tts or cartesia.TTS(voice_id, speed)
    ilock = threading.Lock()

    def one(item):
        k, s, lang = item
        audio = tts.synth(hashing.for_cartesia(s), lang)
        audio = cartesia.normalize_peak(audio)
        (out_dir / f"{k}.mp3").write_bytes(audio)
        with ilock:
            index[k] = s
        return k

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(one, it): it for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
                summary["generated"] += 1
            except Exception as e:
                summary["failed"] += 1
                if len(summary["errors"]) < 5:
                    summary["errors"].append(str(e)[:200])
            if progress and i % 20 == 0:
                progress(summary)
            if i % 50 == 0:
                with ilock:
                    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=0, sort_keys=True))
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=0, sort_keys=True))
    summary["model_note"] = getattr(tts, "model_note", None)
    summary["zip"] = str(_zip((row.get("plan") or {}).get("county") or config.county()))
    return summary


def run_background(cid):
    """Kick off generation for a stamped client; status lands in clients.audio."""
    with _lock:
        if cid in _running:
            return False
        _running.add(cid)

    def work():
        try:
            row = db.get(cid)
            if not row or db.status(row) not in ("stamped", "printed"):
                db.update(cid, audio={"state": "error", "error": "Stamp the card first.", "at": _now()})
                return
            db.update(cid, audio={"state": "running", "at": _now()})

            def prog(s):
                db.update(cid, audio={"state": "running", "at": _now(), **{k: s[k] for k in ("total", "to_generate", "generated", "failed")}})
            s = generate(row, progress=prog)
            s.pop("keys", None)
            db.update(cid, audio={"state": "done" if not s["failed"] else "partial", "at": _now(), **s})
        except Exception as e:
            db.update(cid, audio={"state": "error", "error": str(e)[:300], "at": _now()})
        finally:
            with _lock:
                _running.discard(cid)

    threading.Thread(target=work, daemon=True).start()
    return True
