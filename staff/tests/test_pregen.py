"""Cartesia pre-generation: dry run has no misses (incl. re-plans after blocking each edge of route A); mocked synthesis."""
import json

import pytest

from ember_engine.core import cues as cuemod
from ember_engine.core import hashing, router, shared


def _independent_replan_texts(row, bundle):
    """Every cue text the core produces for the plan and for re-plans after blocking each edge of route A once."""
    plan, profile = row["plan"], row["profile"]
    texts = set()
    for c in plan["choices"]:
        texts |= {q["text"] for q in c["cues"]}
    prof = router.Profile(shared.profile_key_for(profile), shared.battery_pct_for(profile))
    a = plan["choices"][row["selected"][0]]["route"]
    n_replans = 0
    for ei in a["edges"]:
        for c in router.choose(bundle.graph, bundle.refuges, prof, plan["origin"]["node"], plan["fire_bearing_deg"],
                               None, frozenset({ei})):
            texts |= {q["text"] for q in cuemod.build_cues(bundle.graph, c["route"], c["refuge"]["name"])}
            n_replans += 1
    assert n_replans > 0
    return texts


@pytest.mark.parametrize("cid", ["c_rosa", "c_harold", "c_margaret", "c_june", "c_lupe"])
def test_dry_run_has_no_misses(sample, cid):
    from ember_staff import db, engine_client, pregen, workflow
    workflow.stamp(cid, "Dana", attested=True)
    row = db.get(cid)
    bundle = engine_client.bundle()
    have = pregen.keys(pregen.collect(row))
    must = _independent_replan_texts(row, bundle)
    # card text, shelter, devices, fixed phrases, numbers
    must |= set(sum((v for v in row["text"]["sections"].values()), []))
    must |= set(row["plan"]["shelter"]["steps"]) | {d["sentence"] for d in row["plan"]["devices"]}
    must |= set(shared.phrases()["fixed"]) | {str(n) for n in range(1, 501)}
    a = row["plan"]["choices"][0]
    must.add(shared.phrases()["templates"]["choose"].format(refuge=a["refuge"]["name"], n=a["route"]["minutes"]))
    street = next(q["vars"]["street"] for q in a["cues"] if "street" in q["vars"])
    must.add(shared.phrases()["templates"]["blocking"].format(street=street))
    must.add(f"Keep going on {street} for")
    missing = [t for t in must if hashing.clip_key(t) not in have]
    assert not missing, missing[:10]
    s = pregen.generate(row, dry_run=True)
    assert s["total"] == len(have) and s["to_generate"] == s["total"]


def test_dry_run_bedbound(sample):
    from ember_staff import db, pregen
    row = db.get("c_walter")
    strings = pregen.collect(row)
    assert "Call 911. Say: I am in the main bedroom." in strings
    assert any(s.startswith("Your ventilator battery lasts") for s in strings)


class FakeTTS:
    def __init__(self):
        self.sent = []
        self.model_note = None

    def synth(self, text, language="en"):
        self.sent.append((text, language))
        return b"ID3fake-mp3"


def test_generate_writes_clips_index_and_zip(sample, monkeypatch):
    from ember_staff import cartesia, config, db, pregen, workflow
    monkeypatch.setattr(cartesia, "normalize_peak", lambda b, target_dbfs=-1.0: b)
    monkeypatch.setenv("CARTESIA_VOICE_ID", "calm-voice")
    workflow.stamp("c_harold", "Dana", attested=False)
    row = db.get("c_harold")
    tts = FakeTTS()
    s = pregen.generate(row, tts=tts)
    assert s["failed"] == 0 and s["generated"] == s["total"] == len(tts.sent)
    audio = config.bundle_dir() / "audio"
    index = json.loads((audio / "index.json").read_text())
    assert len(index) == s["total"]
    for k, text in list(index.items())[:20]:
        assert hashing.clip_key(text) == k and (audio / f"{k}.mp3").exists()
    # pronunciation map applied only to what is sent; the key stays on the original text
    sent = {t for t, _ in tts.sent}
    assert any("Road" in t for t in sent) and not any(t.endswith(" Rd.") for t in sent)
    # second run skips existing clips
    tts2 = FakeTTS()
    s2 = pregen.generate(row, tts=tts2)
    assert s2["generated"] == 0 and s2["existing"] == s2["total"] and not tts2.sent
    assert (config.bundles_dir() / "fake.zip").exists()


def test_clone_voice_goes_to_client_dir(sample, monkeypatch):
    from ember_staff import cartesia, config, db, pregen
    monkeypatch.setattr(cartesia, "normalize_peak", lambda b, target_dbfs=-1.0: b)
    p = db.get("c_june")["profile"]
    p["voice"] = {"kind": "clone", "voice_id": "v_clone", "consent_name": "Min", "recorded_at": "2026-10-23T00:00:00Z"}
    db.upsert_profile(p)
    row = db.get("c_june")
    out_dir, voice, speed = pregen.audio_dir(row)
    assert out_dir == config.bundle_dir() / "audio" / "clients" / "c_june" and voice == "v_clone" and speed is None
    pregen.generate(row, tts=FakeTTS())
    assert (out_dir / "index.json").exists()


def test_tts_request_shape(monkeypatch):
    from ember_staff import cartesia
    import httpx
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"ID3")
    t = cartesia.TTS("voice-1", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert t.synth("Turn left onto Clark Road.") == b"ID3"
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.cartesia.ai/tts/bytes"
    assert req.headers["Cartesia-Version"] and req.headers["Authorization"] == "Bearer k"
    assert body["model_id"] == "sonic-2" and body["voice"] == {"id": "voice-1"}
    assert body["output_format"] == {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}
    assert body["generation_config"]["speed"] == 0.85
