import pytest

from src.privacy import PLACEHOLDER, ner_backend, scrub_quote

TEXT = ("Joe Kennedy said he and 50 others sheltered in the Kmart parking lot on Clark Road "
        "while Paradise burned. Mrs. Lopez drove to Lake Concow.")


@pytest.mark.parametrize("heuristic", [False, True], ids=["spacy", "heuristic"])
def test_names_removed_places_kept(heuristic):
    out = scrub_quote(TEXT, "Kmart parking lot on Clark Road", force_heuristic=heuristic)
    assert "Kennedy" not in out and "Joe" not in out and "Lopez" not in out
    assert out.count(PLACEHOLDER) == 2
    for place in ("Kmart parking lot", "Clark Road", "Paradise", "Lake Concow"):
        assert place in out


@pytest.mark.parametrize("heuristic", [False, True], ids=["spacy", "heuristic"])
def test_said_name_pattern(heuristic):
    q = '"We just sat in the water," said Maria Gonzalez, 62, who waited out the flames in Lake Concow.'
    out = scrub_quote(q, "Lake Concow", force_heuristic=heuristic)
    assert "Maria" not in out and "Gonzalez" not in out
    assert "Lake Concow" in out and "62" in out  # what happened stays


@pytest.mark.parametrize("heuristic", [False, True], ids=["spacy", "heuristic"])
def test_no_names_unchanged(heuristic):
    q = "Nurses from Feather River Hospital moved patients to the Walgreens lot."
    assert scrub_quote(q, "Walgreens lot", force_heuristic=heuristic) == q


def test_street_named_after_person_is_kept():
    # en_core_web_sm tags "Clark Road" as PERSON; the place-word guard keeps it.
    assert "Clark Road" in scrub_quote("They parked on Clark Road and waited.", None)
    assert "Skyway" in scrub_quote("Traffic stopped on the Skyway near Neal Road.", None)


def test_place_name_span_is_kept():
    q = "Dozens sheltered at Walgreens until morning."
    assert scrub_quote(q, "Walgreens") == q


def test_honorifics():
    out = scrub_quote("Dr. Ann Lee and Officer Smith led people to the field.", "field", force_heuristic=True)
    assert "Lee" not in out and "Smith" not in out and "field" in out


def test_spacy_backend_loaded():
    # The Docker image installs en_core_web_sm; the heuristic is only a fallback.
    assert ner_backend() == "spacy"


def test_empty():
    assert scrub_quote("") == ""
