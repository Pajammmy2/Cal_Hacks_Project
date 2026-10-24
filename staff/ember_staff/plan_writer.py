"""Claude plan writer (spec: Anthropic track, Job 2).

One call per card (+ one back-translation call when a second language is set). The model only ever sees
{placeholders} for street names, refuge names, minutes, numbers and phone numbers; code injects the real values
afterwards and rejects any output that types a digit, invents a placeholder, or drops one. Any failure falls back
to the engine's templated text. The human stamp is required either way.
"""
import json
import re
from datetime import datetime, timezone

from . import config

SYSTEM_PROMPT = (
    "Write evacuation instructions for an older adult or person with a mobility disability. Short sentences. "
    "One action per sentence. Use only the street names, refuge names, and numbers provided; never invent a place "
    "or a number. Keep the step order."
)
BACK_SYSTEM_PROMPT = (
    "Translate each sentence into plain English as literally as you can. Keep every {placeholder} exactly as written. "
    "Do not fix, soften, add or drop anything, especially words like not, never or don't."
)

SECTIONS = ("steps", "steps_b", "shelter", "devices")
LANG_LABELS = {"en": "English", "es": "Spanish", "hmn": "Hmong"}
NEG_RE = re.compile(r"\b(not|never|no|none|nothing|nobody|nowhere|cannot)\b|n't\b", re.I)
PH_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
DIGIT_RE = re.compile(r"\d+(?:[.,]\d+)?")
TOKEN_RE = re.compile(r"\{[a-z][a-z0-9_]*\}|\d+(?:\.\d+)?")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def language_of(profile):
    lang = profile.get("language") or "en"
    if lang == "en":
        return None, None
    if lang == "other":
        label = (profile.get("language_other") or "").strip()
        return ("other", label) if label else (None, None)
    return lang, LANG_LABELS.get(lang, lang)


def target_grade(profile):
    return 4 if profile.get("cognition") == "simple_steps" else 6


def chosen(plan, selected=None):
    """(choice A, choice B or None) honoring staff swaps (selected = [a_index, b_index] into plan.choices)."""
    ch = (plan or {}).get("choices") or []
    if not ch:
        return None, None
    sel = selected or [0, 1]
    a = ch[sel[0]] if sel[0] < len(ch) else ch[0]
    b = ch[sel[1]] if len(sel) > 1 and sel[1] is not None and sel[1] < len(ch) else None
    return a, b


# ---------------------------------------------------------------- placeholders

def _sub_names(text, names):
    """Replace literal names (longest first, whole words) with placeholders, never inside an existing placeholder."""
    for value, key in sorted(names, key=lambda kv: -len(kv[0])):
        if not value:
            continue
        pat = re.compile(r"\{[a-z][a-z0-9_]*\}|(?<![\w])" + re.escape(value) + r"(?![\w])")
        text = pat.sub(lambda m, k=key: m.group(0) if m.group(0).startswith("{") else "{" + k + "}", text)
    return text


class Values:
    """Placeholder registry: name -> real value, built from the plan."""

    def __init__(self):
        self.v = {}
        self._names = []     # (literal, key) for streets/refuges/room
        self._numbers = {}   # literal -> key

    def name(self, key, literal):
        self.v[key] = literal
        self._names.append((literal, key))

    def number(self, literal, key=None):
        literal = str(literal)
        if key:
            self.v[key] = literal
            self._numbers.setdefault(literal, key)
            return key
        if literal not in self._numbers:
            k = f"n_{sum(1 for x in self.v if x.startswith('n_')) + 1}"
            self.v[k] = literal
            self._numbers[literal] = k
        return self._numbers[literal]

    def tokenize(self, text, register=True):
        """Literal sentence -> placeholder sentence. With register=False unknown digits stay literal (for diffs)."""
        out = _sub_names(text, self._names)

        def num(m):
            s = m.group(0)
            if s.startswith("{"):
                return s
            if register:
                return "{" + self.number(s) + "}"
            k = self._numbers.get(s)
            return "{" + k + "}" if k else s
        return re.sub(r"\{[a-z][a-z0-9_]*\}|\d+(?:\.\d+)?", num, out)

    def fill(self, text):
        return PH_RE.sub(lambda m: self.v.get(m.group(1), m.group(0)), text)


def build_input(profile, plan, selected=None):
    """Structured engine steps with placeholders + the values code injects afterwards."""
    vals = Values()
    a, b = chosen(plan, selected)
    streets = []
    for c in (a, b):
        if not c:
            continue
        for cue in c.get("cues") or []:
            s = (cue.get("vars") or {}).get("street")
            if s and s not in streets:
                streets.append(s)
    for i, s in enumerate(streets, 1):
        vals.name(f"street_{i}", s)
    if a:
        vals.name("refuge_a", a["refuge"]["name"])
        vals.number(a["route"]["minutes"], "minutes_a")
    if b:
        vals.name("refuge_b", b["refuge"]["name"])
        vals.number(b["route"]["minutes"], "minutes_b")
    room = ((plan or {}).get("shelter") or {}).get("room")
    if room:
        vals.name("room", room)
    vals.number("911", "emergency_number")
    contacts = []
    for i, c in enumerate((profile.get("contacts") or [])[:3], 1):
        if c.get("phone"):
            vals.name(f"phone_{i}", c["phone"])
        if c.get("name"):
            vals.name(f"contact_{i}", c["name"])
        contacts.append({"name": "{contact_%d}" % i if c.get("name") else None,
                         "phone": "{phone_%d}" % i if c.get("phone") else None,
                         "accessible_vehicle": bool(c.get("accessible_vehicle"))})

    sections = {
        "steps": [vals.tokenize(s) for s in (a or {}).get("card_steps", [])],
        "steps_b": [vals.tokenize(s) for s in (b or {}).get("card_steps", [])],
        "shelter": [vals.tokenize(s) for s in ((plan or {}).get("shelter") or {}).get("steps", [])],
        "devices": [vals.tokenize(d["sentence"]) for d in (plan or {}).get("devices", [])],
    }

    def route(c, key):
        if not c:
            return None
        return {"refuge": "{refuge_%s}" % key, "minutes": "{minutes_%s}" % key, "kind": c["refuge"].get("kind"),
                "cues": [{"template": q["template"], "text": vals.tokenize(q["text"])} for q in c.get("cues") or []],
                "card_steps": sections["steps" if key == "a" else "steps_b"]}

    lang, label = language_of(profile)
    payload = {
        "profile": {
            "mobility": profile.get("mobility"), "transfer": profile.get("transfer"),
            "devices": [d.get("kind") for d in profile.get("devices") or []],
            "cognition_flag": profile.get("cognition") == "simple_steps",
            "language": label or "English",
        },
        "reading_level_target_grade": target_grade(profile),
        "route_a": route(a, "a"),
        "route_b": route(b, "b"),
        "shelter_steps": sections["shelter"],
        "device_sentences": sections["devices"],
        "contacts": contacts,
        "placeholders": sorted(vals.v),
    }
    return payload, vals, sections, (lang, label)


# ---------------------------------------------------------------- validation and diffs

def check_output(arr, required, allowed):
    """Problems with one generated list: digits outside placeholders, unknown or missing placeholders."""
    problems = []
    joined = " ".join(arr)
    found = set(PH_RE.findall(joined))
    stripped = PH_RE.sub(" ", joined)
    if DIGIT_RE.search(stripped):
        problems.append(("digit", f"typed a number: {DIGIT_RE.search(stripped).group(0)!r}"))
    for k in sorted(found - set(allowed)):
        problems.append(("unknown_placeholder", "{" + k + "}"))
    for k in sorted(set(required) - found):
        problems.append(("missing_placeholder", "{" + k + "}"))
    if required and not arr:
        problems.append(("empty", "no sentences"))
    for s in arr:
        if "{" in PH_RE.sub("", s) or "}" in PH_RE.sub("", s):
            problems.append(("broken_placeholder", s[:80]))
    return problems


def negations(text):
    return len(NEG_RE.findall(text.replace("’", "'")))


UNIT_WORDS = {"meter": "m", "meters": "m", "metre": "m", "metres": "m", "m": "m", "km": "km", "kilometer": "km",
              "kilometers": "km", "kilometre": "km", "kilometres": "km", "mile": "mi", "miles": "mi", "foot": "ft",
              "feet": "ft", "ft": "ft", "yard": "yd", "yards": "yd", "block": "block", "blocks": "block",
              "minute": "min", "minutes": "min", "min": "min", "hour": "h", "hours": "h"}
UNIT_RE = re.compile(r"\b(" + "|".join(sorted(UNIT_WORDS, key=len, reverse=True)) + r")\b", re.I)


def units(text):
    """Distance/time unit words in a sentence, normalized (a translation that turns meters into miles must be caught)."""
    return {UNIT_WORDS[m.lower()] for m in UNIT_RE.findall(PH_RE.sub(" ", text))}


def _tokens(text):
    return sorted(TOKEN_RE.findall(text))


def diff_back(en, back, l2=None):
    """Compare English source sentences with the back-translation (all already tokenized to placeholders).

    Flags dropped/added negations, changed digits, changed distance/time units, missing placeholders, and
    sentence-count changes.
    Returns [(index, kind, detail)]."""
    issues = []
    if len(en) != len(back):
        issues.append((None, "count", f"{len(en)} English sentences, {len(back)} back-translated"))
    if l2 is not None and len(l2) != len(en):
        issues.append((None, "count", f"{len(en)} English sentences, {len(l2)} translated"))
    for i in range(max(len(en), len(back))):
        e = en[i] if i < len(en) else ""
        b = back[i] if i < len(back) else ""
        ne, nb = negations(e), negations(b)
        if nb < ne:
            issues.append((i, "negation_dropped", f"'not/never/don't' in English ({ne}) missing in back-translation ({nb})"))
        elif nb > ne:
            issues.append((i, "negation_added", f"back-translation has a negation the English does not"))
        de = sorted(DIGIT_RE.findall(PH_RE.sub(" ", e)))
        db_ = sorted(DIGIT_RE.findall(PH_RE.sub(" ", b)))
        if de != db_:
            issues.append((i, "digit_changed", f"numbers {de} became {db_}"))
        ue, ub = units(e), units(b)
        if ue != ub:
            issues.append((i, "unit_changed", f"units {sorted(ue)} became {sorted(ub)}"))
        pe, pb = set(PH_RE.findall(e)), set(PH_RE.findall(b))
        if pe - pb:
            issues.append((i, "placeholder_missing", "missing " + ", ".join("{%s}" % k for k in sorted(pe - pb))))
        if pb - pe:
            issues.append((i, "placeholder_changed", "extra " + ", ".join("{%s}" % k for k in sorted(pb - pe))))
        if l2 is not None and i < len(l2):
            p2 = set(PH_RE.findall(l2[i]))
            if pe - p2:
                issues.append((i, "placeholder_missing_l2", "translation missing " + ", ".join("{%s}" % k for k in sorted(pe - p2))))
            d2 = sorted(DIGIT_RE.findall(PH_RE.sub(" ", l2[i])))
            if d2 != de:
                issues.append((i, "digit_changed_l2", f"numbers {de} became {d2} in the translation"))
    return issues


def readability(sentences, vals):
    """Flesch-Kincaid grade of the sentences with names replaced by a one-syllable word."""
    try:
        import textstat
    except ImportError:  # pragma: no cover
        return None
    text = " ".join(PH_RE.sub("Main", vals.tokenize(s, register=False)) for s in sentences if s)
    if not text.strip():
        return None
    return round(float(textstat.flesch_kincaid_grade(text)), 1)


# ---------------------------------------------------------------- Claude calls

def _client():
    key = config.env("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=1)


def _call_claude(system, user_text, tool):
    """Structured output via a forced tool call. Returns the tool input dict. Raises on any failure."""
    import anthropic
    client = _client()
    if client is None:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    kwargs = dict(model=config.claude_model(), max_tokens=4096, system=system,
                  messages=[{"role": "user", "content": user_text}], tools=[tool])
    try:
        msg = client.messages.create(tool_choice={"type": "tool", "name": tool["name"]}, **kwargs)
    except anthropic.BadRequestError as e:
        if "tool_choice" not in str(e):
            raise
        # newer models reject forced tool_choice: fall back to auto + strict schema + an explicit instruction
        strict_tool = dict(tool, strict=True)
        kwargs["tools"] = [strict_tool]
        kwargs["messages"] = [{"role": "user", "content": user_text + f"\n\nAnswer only by calling the {tool['name']} tool."}]
        msg = client.messages.create(tool_choice={"type": "auto"}, **kwargs)
    if getattr(msg, "stop_reason", None) == "refusal":
        raise RuntimeError("model refused")
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
            data = block.input
            return data if isinstance(data, dict) else json.loads(data)
    raise RuntimeError("no tool_use block in response")


def _arr():
    return {"type": "array", "items": {"type": "string"}}


def writer_tool(with_l2):
    props = {"steps_en": _arr(), "steps_b_en": _arr(), "shelter_en": _arr(), "devices_en": _arr()}
    req = list(props)
    if with_l2:
        for k in ("steps_l2", "steps_b_l2", "shelter_l2", "devices_l2"):
            props[k] = _arr()
            req.append(k)
    return {"name": "write_plan_card",
            "description": "Return the plan card sentences. Keep every {placeholder}; never type a digit.",
            "input_schema": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}


BACK_KEYS = ("steps_l2", "steps_b_l2", "shelter_l2", "devices_l2")
# Output keys end in _en so the model does not just copy the input lists back (claude-sonnet-4-6 did exactly that
# when the output keys were also *_l2).
BACK_TOOL = {"name": "back_translate",
             "description": "Return the literal ENGLISH translation of each list, sentence for sentence. "
                            "Never return the original non-English sentences.",
             "input_schema": {"type": "object",
                              "properties": {k.replace("_l2", "_en"): dict(_arr(), description=f"English translation of {k}")
                                             for k in BACK_KEYS},
                              "required": [k.replace("_l2", "_en") for k in BACK_KEYS],
                              "additionalProperties": False}}


def back_lists(back, back_in):
    """Map the back-translation tool output onto the *_l2 keys; raise if the model echoed the input."""
    out = {k: list(back.get(k.replace("_l2", "_en")) or back.get(k) or []) for k in back_in}
    echoed = [k for k in back_in if back_in[k] and out[k] == list(back_in[k])]
    if echoed:
        raise ValueError(f"back-translation echoed the input for {', '.join(echoed)}")
    return out


def writer_user_message(payload, label):
    lines = [
        "Rewrite the engine's plan below for the printed card and the phone.",
        "Return four lists: steps_en (route A card steps, 4 to 7 sentences, same order as route_a.card_steps), "
        "steps_b_en (route B, same rules; empty if there is no route B), shelter_en (the shelter steps, same order), "
        "devices_en (one sentence or two per device sentence, same order).",
        "Every street name, refuge name, room, phone number and number is a {placeholder}. Copy placeholders exactly. "
        "Use every placeholder that appears in a source list in your version of that list. Never type a digit or a "
        "number word for a quantity, never make up a placeholder.",
        f"Reading level: grade {payload['reading_level_target_grade']} or lower.",
    ]
    if label:
        lines.append(f"Also return steps_l2, steps_b_l2, shelter_l2 and devices_l2: a {label} translation of your English "
                     "lists, one sentence for each English sentence, same placeholders.")
    lines.append("Engine plan (JSON):")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=1))
    return "\n".join(lines)


# ---------------------------------------------------------------- public API

def templated(profile, plan, selected=None, note=None):
    """Engine templated text (no Claude). Used for run-all, no key, API down, or rejected output."""
    payload, vals, sections, (lang, label) = build_input(profile, plan, selected)
    rec = _record(profile, vals, "template", {
        "steps_en": [vals.fill(s) for s in sections["steps"]],
        "steps_b_en": [vals.fill(s) for s in sections["steps_b"]],
        "shelter_en": [vals.fill(s) for s in sections["shelter"]],
        "devices_en": [vals.fill(s) for s in sections["devices"]],
    }, lang, label)
    if note:
        rec["error"] = note
    if lang:
        rec["issues"].append({"section": "steps_l2", "index": None, "kind": "no_translation", "severity": "warn",
                              "detail": f"No {label} text (Claude not used). Card prints in English."})
    return finish(rec, vals)


def _record(profile, vals, source, sections, lang, label):
    return {"source": source, "language": lang, "language_label": label, "target_grade": target_grade(profile),
            "sections": sections, "back": {}, "values": dict(vals.v), "issues": [], "edited": [],
            "generated_at": _now(), "model": config.claude_model() if source == "claude" else None}


def generate(profile, plan, selected=None, use_claude=True):
    """Full plan-writer pass with fallback. Never raises for Claude problems."""
    if not plan or not use_claude or not config.env("ANTHROPIC_API_KEY"):
        return templated(profile, plan, selected, None if not use_claude else
                         ("Claude not configured (no ANTHROPIC_API_KEY): engine templated text." if plan else None))
    payload, vals, sections, (lang, label) = build_input(profile, plan, selected)
    allowed = set(vals.v)
    try:
        out = _call_claude(SYSTEM_PROMPT, writer_user_message(payload, label), writer_tool(bool(lang)))
    except Exception as e:  # API down, key revoked, timeout, refusal
        return templated(profile, plan, selected, f"Claude unavailable ({type(e).__name__}): engine templated text.")

    problems = []
    keys = [("steps_en", "steps"), ("steps_b_en", "steps_b"), ("shelter_en", "shelter"), ("devices_en", "devices")]
    if lang:
        keys += [("steps_l2", "steps"), ("steps_b_l2", "steps_b"), ("shelter_l2", "shelter"), ("devices_l2", "devices")]
    for k, src in keys:
        arr = out.get(k)
        if not isinstance(arr, list) or not all(isinstance(s, str) for s in arr):
            problems.append((k, "schema", "missing or not a list of strings"))
            continue
        for kind, detail in check_output(arr, set(PH_RE.findall(" ".join(sections[src]))), allowed):
            problems.append((k, kind, detail))
    if problems:
        rec = templated(profile, plan, selected, "Claude output rejected: engine templated text.")
        for k, kind, detail in problems:
            rec["issues"].append({"section": k, "index": None, "kind": "rejected_" + kind, "severity": "error",
                                  "detail": detail})
        return finish(rec, vals)

    rec = _record(profile, vals, "claude", {k: [vals.fill(s) for s in out[k]] for k, _ in keys}, lang, label)
    if lang:
        try:
            back_in = {k: out[k] for k in BACK_KEYS}
            back = _call_claude(BACK_SYSTEM_PROMPT,
                                f"Translate these {label} sentences into English. Put the English in steps_en, "
                                f"steps_b_en, shelter_en and devices_en. JSON:\n" + json.dumps(back_in, ensure_ascii=False),
                                BACK_TOOL)
            rec["back"] = {k: [vals.fill(s) for s in v] for k, v in back_lists(back, back_in).items()}
        except Exception as e:
            rec["back"] = {}
            rec["issues"].append({"section": "steps_l2", "index": None, "kind": "back_translation_failed",
                                  "severity": "error", "detail": f"Back-translation call failed ({type(e).__name__})."})
    return finish(rec, vals)


def values_obj(rec):
    """Rebuild the placeholder registry from a stored record (for re-checking after edits)."""
    vals = Values()
    for k, v in (rec.get("values") or {}).items():
        if k.startswith(("street_", "refuge_", "room", "phone_", "contact_")):
            vals.name(k, v)
        else:
            vals.number(v, k)
    return vals


def finish(rec, vals=None):
    """(Re)compute back-translation diffs and readability; set needs_review."""
    vals = vals or values_obj(rec)
    keep = [i for i in rec["issues"] if not i["kind"].startswith(("negation", "digit", "unit", "placeholder", "count", "reading"))]
    rec["issues"] = keep
    S = rec["sections"]
    if rec.get("language") and rec.get("back"):
        for sec in ("steps", "steps_b", "shelter", "devices"):
            en = [vals.tokenize(s, register=False) for s in S.get(f"{sec}_en", [])]
            l2k = f"{sec}_l2"
            l2 = [vals.tokenize(s, register=False) for s in S.get(l2k, [])] if l2k in S else None
            back = [vals.tokenize(s, register=False) for s in rec["back"].get(l2k, [])]
            for idx, kind, detail in diff_back(en, back, l2):
                rec["issues"].append({"section": l2k, "index": idx, "kind": kind, "severity": "error", "detail": detail})
    grades = {}
    for sec in ("steps_en", "steps_b_en", "shelter_en", "devices_en"):
        g = readability(S.get(sec, []), vals)
        if g is not None:
            grades[sec] = g
            if g > rec["target_grade"]:
                rec["issues"].append({"section": sec, "index": None, "kind": "reading_level", "severity": "warn",
                                      "detail": f"grade {g} is above the target grade {rec['target_grade']}"})
    rec["readability"] = grades
    rec["needs_review"] = any(i["severity"] == "error" for i in rec["issues"])
    return rec


def edit_sentence(rec, section, index, text):
    S = rec["sections"]
    if section not in S or not (0 <= index < len(S[section])):
        raise KeyError(section)
    S[section][index] = " ".join(text.split())
    tag = f"{section}:{index}"
    if tag not in rec["edited"]:
        rec["edited"].append(tag)
    return finish(rec)
