"""Plan writer (Job 2) with Claude mocked: placeholders, rejection, back-translation diff with seeded errors."""
import pytest

from ember_staff import plan_writer as pw


@pytest.fixture
def rosa(sample):
    from ember_staff import db
    return db.get("c_rosa")


def _good_output(sections, l2=True):
    out = {"steps_en": list(sections["steps"]), "steps_b_en": list(sections["steps_b"]),
           "shelter_en": list(sections["shelter"]) + ["Do not open the windows."], "devices_en": list(sections["devices"])}
    if l2:
        for k in ("steps", "steps_b", "shelter", "devices"):
            out[f"{k}_l2"] = ["ES " + s for s in out[f"{k}_en"]]
    return out


def _mock(monkeypatch, writer, back=None, calls=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def fake(system, user, tool):
        if calls is not None:
            calls.append((system, user, tool))
        if tool["name"] == "write_plan_card":
            return writer
        return back
    monkeypatch.setattr(pw, "_call_claude", fake)


def test_input_uses_placeholders_not_literals(rosa):
    payload, vals, sections, (lang, label) = pw.build_input(rosa["profile"], rosa["plan"], rosa["selected"])
    assert lang == "es" and label == "Spanish"
    import json
    blob = json.dumps(payload)
    for literal in ("Pearson Rd", "the Safeway lot", "Bille Park", "530-555", "back bedroom", "911"):
        assert literal not in blob, literal
    import re
    assert not re.search(r"\d", re.sub(r"\{[a-z0-9_]+\}", "", " ".join(sum(sections.values(), []))))
    assert vals.v["refuge_a"] == "the Safeway lot" and vals.v["minutes_a"] == "6"
    assert payload["reading_level_target_grade"] == 6
    assert "{refuge_a}" in sections["steps"][-1]


def test_good_output_is_filled_and_back_translation_clean(rosa, monkeypatch):
    _, vals, sections, _ = pw.build_input(rosa["profile"], rosa["plan"], rosa["selected"])
    writer = _good_output(sections)
    back = {k: [s for s in writer[k.replace("_l2", "_en")]] for k in ("steps_l2", "steps_b_l2", "shelter_l2", "devices_l2")}
    calls = []
    _mock(monkeypatch, writer, back, calls)
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])
    assert rec["source"] == "claude"
    assert calls[0][0] == pw.SYSTEM_PROMPT and len(calls) == 2
    assert rec["sections"]["steps_en"][0].startswith("Start on Pearson Rd.")
    assert rec["sections"]["steps_en"][-1] == "Arrive at the Safeway lot."
    assert rec["sections"]["shelter_en"][-2] == "Call 911. Say: I am in the back bedroom."
    assert not rec["needs_review"], rec["issues"]


def test_seeded_back_translation_errors_are_caught(rosa, monkeypatch):
    _, vals, sections, _ = pw.build_input(rosa["profile"], rosa["plan"], rosa["selected"])
    writer = _good_output(sections)
    back = {k: list(writer[k.replace("_l2", "_en")]) for k in ("steps_l2", "steps_b_l2", "shelter_l2", "devices_l2")}
    neg_i = len(back["shelter_l2"]) - 1
    assert back["shelter_l2"][neg_i] == "Do not open the windows."
    back["shelter_l2"][neg_i] = "Open the windows."                             # dropped "not"
    i_num = next(i for i, s in enumerate(back["steps_l2"]) if "{n_" in s)
    import re
    back["steps_l2"][i_num] = re.sub(r"\{n_\d+\}", "47", back["steps_l2"][i_num], count=1)   # changed number
    i_st = next(i for i, s in enumerate(back["steps_b_l2"]) if "{street_" in s)
    back["steps_b_l2"][i_st] = re.sub(r"\{street_\d+\}", "the road", back["steps_b_l2"][i_st], count=1)  # lost placeholder
    _mock(monkeypatch, writer, back)
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])
    kinds = {(i["section"], i["index"], i["kind"]) for i in rec["issues"]}
    assert ("shelter_l2", neg_i, "negation_dropped") in kinds
    assert ("steps_l2", i_num, "digit_changed") in kinds
    assert ("steps_b_l2", i_st, "placeholder_missing") in kinds
    assert rec["needs_review"] is True


@pytest.mark.parametrize("variant", ["dont", "never", "contraction"])
def test_negation_variants(variant):
    en = {"dont": "Don't use the elevator.", "never": "Never go back inside.", "contraction": "You can't stay in the car."}[variant]
    back = {"dont": "Use the elevator.", "never": "Go back inside.", "contraction": "You can stay in the car."}[variant]
    issues = pw.diff_back([en], [back])
    assert any(k == "negation_dropped" for _, k, _ in issues)
    assert pw.diff_back([en], [en]) == []


@pytest.mark.parametrize("seed,kind", [
    ("digit", "rejected_digit"),
    ("unknown", "rejected_unknown_placeholder"),
    ("missing", "rejected_missing_placeholder"),
])
def test_bad_writer_output_falls_back_to_templated_text(rosa, monkeypatch, seed, kind):
    _, vals, sections, _ = pw.build_input(rosa["profile"], rosa["plan"], rosa["selected"])
    writer = _good_output(sections)
    if seed == "digit":
        writer["steps_en"][0] = writer["steps_en"][0] + " It is 3 blocks."
    elif seed == "unknown":
        writer["steps_en"][0] = "Go past {church_7}."
    else:
        writer["steps_en"][-1] = "Arrive at the lot."          # dropped {refuge_a}
    _mock(monkeypatch, writer, None)
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])
    assert rec["source"] == "template" and rec["needs_review"]
    assert any(i["kind"] == kind for i in rec["issues"]), rec["issues"]
    assert rec["sections"]["steps_en"] == rosa["plan"]["choices"][0]["card_steps"]


def test_api_down_or_no_key_uses_templated_text(rosa, monkeypatch):
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])          # no key
    assert rec["source"] == "template" and "ANTHROPIC_API_KEY" in rec["error"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "revoked")

    def boom(*a):
        raise RuntimeError("401 invalid x-api-key")
    monkeypatch.setattr(pw, "_call_claude", boom)
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])
    assert rec["source"] == "template" and "unavailable" in rec["error"]


def test_reading_level_flag(sample):
    from ember_staff import db
    m = db.get("c_margaret")              # cognition flag -> grade 4 target
    rec = m["text"]
    assert rec["target_grade"] == 4
    hard = ("Subsequently, notwithstanding considerable environmental deterioration, proceed expeditiously "
            "toward the designated congregation location immediately.")
    rec = pw.edit_sentence(rec, "steps_en", 0, hard)
    assert any(i["kind"] == "reading_level" and i["section"] == "steps_en" for i in rec["issues"])


def test_edit_rechecks_against_back_translation(rosa, monkeypatch):
    _, vals, sections, _ = pw.build_input(rosa["profile"], rosa["plan"], rosa["selected"])
    writer = _good_output(sections)
    back = {k: list(writer[k.replace("_l2", "_en")]) for k in ("steps_l2", "steps_b_l2", "shelter_l2", "devices_l2")}
    _mock(monkeypatch, writer, back)
    rec = pw.generate(rosa["profile"], rosa["plan"], rosa["selected"])
    assert not rec["needs_review"]
    i = len(rec["sections"]["shelter_en"]) - 1
    rec = pw.edit_sentence(rec, "shelter_en", i, "Do not open the windows. Never go outside.")
    assert rec["needs_review"]
