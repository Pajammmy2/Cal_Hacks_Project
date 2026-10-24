"""Privacy rule: store places and what happened, never who.

Every quote passes through `scrub_quote` before it is stored or pushed. It removes person names
with a small NER pass (spaCy `en_core_web_sm`, PERSON entities) plus a regex backstop for
honorific + name patterns ("Mrs. Lopez", "Dr. Ann Lee"). Removed names become "[person]".

Guards (because small NER models mislabel places as people, e.g. "Clark Road" -> PERSON):
  - a PERSON span whose last word is a place word (Road, Lake, Park, School, ...) is kept;
  - a PERSON span that is part of the extracted place name ("Kmart", "Walgreens") is kept.

If spaCy or the model cannot be loaded, a documented heuristic is used instead (honorifics,
"said <Name>", "<Name> said", capitalized two-word names not followed by a place word).
Both paths are covered by tests/test_privacy.py.
"""

from __future__ import annotations

import functools
import logging
import re

log = logging.getLogger(__name__)

PLACEHOLDER = "[person]"

PLACE_WORDS = {
    "road", "rd", "street", "st", "avenue", "ave", "boulevard", "blvd", "drive", "dr", "lane", "ln",
    "way", "highway", "hwy", "route", "parkway", "pkwy", "court", "ct", "circle", "trail", "loop",
    "lake", "reservoir", "river", "creek", "pond", "park", "field", "fields", "meadow", "ranch",
    "school", "college", "university", "church", "hospital", "center", "centre", "hall", "mall",
    "plaza", "lot", "store", "market", "station", "airport", "campus", "stadium", "library",
    "county", "city", "town", "valley", "ridge", "hill", "hills", "canyon", "mountain", "bridge",
    "dam", "marina", "beach", "estates", "village", "springs", "fairgrounds", "casino", "hotel",
    "motel", "inn", "winery", "vineyard", "farm", "cemetery", "golf", "course", "club",
}

HONORIFIC = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Rev|Sgt|Capt|Lt|Officer|Deputy|Chief|Sheriff|Pastor|Father)\.?"
NAME = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
_HONORIFIC_RE = re.compile(rf"\b{HONORIFIC}\s+{NAME}(?:\s+{NAME})?")
_SAID_AFTER_RE = re.compile(rf"\b(said|says|recalled|told|added|explained)\s+({NAME}(?:\s+{NAME})+)")
_SAID_BEFORE_RE = re.compile(rf"\b({NAME}(?:\s+{NAME})+)\s+(said|says|recalled|told|added|explained)\b")
_TWO_CAPS_RE = re.compile(rf"\b({NAME})\s+({NAME})\b")

COMMON_FIRST_NAMES = {
    "john", "mary", "james", "patricia", "robert", "jennifer", "michael", "linda", "william",
    "elizabeth", "david", "barbara", "richard", "susan", "joseph", "jessica", "thomas", "sarah",
    "charles", "karen", "christopher", "nancy", "daniel", "lisa", "matthew", "betty", "anthony",
    "margaret", "mark", "sandra", "donald", "ashley", "steven", "kimberly", "paul", "emily",
    "andrew", "donna", "joshua", "michelle", "kenneth", "dorothy", "kevin", "carol", "brian",
    "amanda", "george", "melissa", "edward", "deborah", "ronald", "stephanie", "timothy",
    "rebecca", "jason", "sharon", "jeffrey", "laura", "ryan", "cynthia", "jacob", "kathleen",
    "gary", "amy", "nicholas", "shirley", "eric", "angela", "jonathan", "helen", "stephen",
    "anna", "larry", "brenda", "justin", "pamela", "scott", "nicole", "brandon", "emma",
    "benjamin", "samantha", "samuel", "katherine", "frank", "christine", "gregory", "debra",
    "raymond", "rachel", "alexander", "catherine", "patrick", "carolyn", "jack", "janet",
    "dennis", "ruth", "jerry", "maria", "tyler", "heather", "aaron", "diane", "jose", "virginia",
    "adam", "julie", "henry", "joyce", "nathan", "victoria", "douglas", "olivia", "zachary",
    "kelly", "peter", "christina", "kyle", "lauren", "walter", "joan", "ethan", "evelyn", "jeremy",
    "judith", "harold", "megan", "keith", "cheryl", "christian", "andrea", "roger", "hannah",
    "noah", "martha", "gerald", "jacqueline", "carl", "frances", "terry", "gloria", "sean", "ann",
    "austin", "teresa", "arthur", "kathryn", "lawrence", "sara", "jesse", "janice", "dylan",
    "jean", "bryan", "alice", "joe", "madison", "jordan", "doris", "billy", "abigail", "bruce",
    "julia", "albert", "judy", "willie", "grace", "gabriel", "denise", "logan", "amber", "alan",
    "marilyn", "juan", "beverly", "wayne", "danielle", "roy", "theresa", "ralph", "sophia",
    "randy", "marie", "eugene", "diana", "vincent", "brittany", "russell", "natalie", "elijah",
    "isabella", "louis", "charlotte", "bobby", "rose", "philip", "alexis", "johnny", "kayla",
    "luis", "carlos", "miguel", "ana", "rosa", "tina", "tom", "bob", "jim", "mike", "dave",
    "steve", "chris", "tony", "rick", "dan", "ken", "ron", "don", "bill", "sue", "pat", "kim",
}


def _is_place_like(span: str, place: str | None) -> bool:
    words = re.findall(r"[A-Za-z]+", span)
    if not words:
        return True
    if words[-1].lower() in PLACE_WORDS:
        return True
    # Part of the extracted place name ("Kmart", "Walgreens on Clark Rd") -> it's the place, keep it.
    return bool(place) and span.strip().lower() in place.lower()


@functools.lru_cache(maxsize=1)
def _load_nlp():
    try:
        import spacy  # type: ignore

        return spacy.load("en_core_web_sm", disable=["lemmatizer"])
    except Exception as exc:  # pragma: no cover - exercised via force_heuristic in tests
        log.warning("spaCy en_core_web_sm unavailable (%s); using heuristic name stripping", exc)
        return None


def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for start, end in sorted(spans, reverse=True):
        out = out[:start] + PLACEHOLDER + out[end:]
    return out


def _ner_spans(text: str, place: str | None) -> list[tuple[int, int]] | None:
    nlp = _load_nlp()
    if nlp is None:
        return None
    doc = nlp(text)
    spans = []
    for ent in doc.ents:
        if ent.label_ == "PERSON" and not _is_place_like(ent.text, place):
            spans.append((ent.start_char, ent.end_char))
    return spans


def _heuristic_spans(text: str, place: str | None) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _HONORIFIC_RE.finditer(text):
        spans.append((m.start(), m.end()))
    for m in _SAID_AFTER_RE.finditer(text):
        if not _is_place_like(m.group(2), place):
            spans.append((m.start(2), m.end(2)))
    for m in _SAID_BEFORE_RE.finditer(text):
        if not _is_place_like(m.group(1), place):
            spans.append((m.start(1), m.end(1)))
    for m in _TWO_CAPS_RE.finditer(text):
        if m.group(1).lower() in COMMON_FIRST_NAMES and not _is_place_like(m.group(0), place):
            spans.append((m.start(), m.end()))
    return spans


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def scrub_quote(text: str, place: str | None = None, *, force_heuristic: bool = False) -> str:
    """Return `text` with person names replaced by "[person]"."""
    if not text:
        return text
    spans = (None if force_heuristic else _ner_spans(text, place)) or []
    # The heuristic backstop always runs: small NER models miss "Mrs. Lopez"-style names.
    spans += _heuristic_spans(text, place)
    out = _replace_spans(text, _merge(spans))
    return re.sub(r"\s{2,}", " ", out).strip()


def ner_backend() -> str:
    """'spacy' when en_core_web_sm is loaded, else 'heuristic' (reported in summary.json)."""
    return "spacy" if _load_nlp() is not None else "heuristic"
