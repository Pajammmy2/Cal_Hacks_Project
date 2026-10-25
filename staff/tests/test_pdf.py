"""Printed card: Letter, one sheet (one page, two at most), body type never below 14 pt."""
import io
import re

import pytest
from pypdf import PdfReader


def _stamp(cid):
    from ember_staff import workflow
    workflow.stamp(cid, "Dana", attested=True)


@pytest.mark.parametrize("cid", ["c_rosa", "c_harold", "c_margaret", "c_walter", "c_june", "c_lupe"])
def test_pdf_is_letter_on_one_sheet(sample, cid):
    from ember_staff import db, pdf
    _stamp(cid)
    data, pages, level = pdf.render_pdf(db.get(cid))
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == pages <= 2
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        assert (round(w), round(h)) == (612, 792)          # US Letter in points


@pytest.mark.parametrize("cid,body", [("c_rosa", 16), ("c_margaret", 18), ("c_june", 18)])
def test_type_sizes_never_shrink(sample, cid, body):
    from ember_staff import db, pdf
    row = db.get(cid)
    for level in range(pdf.MAX_TIGHTEN + 1):
        html = pdf.render_html(row, tighten=level)
        assert "font-size: 28pt" in html and "font-size: 20pt" in html
        sizes = [int(s) for s in re.findall(r"font-size:\s*(\d+)pt", html)]
        assert min(sizes) >= 14                      # owner: body never below 14 pt
        if level == 0:
            assert f"font-size: {body}pt" in html


def test_card_content(sample):
    from ember_staff import db, pdf
    _stamp("c_harold")
    html = pdf.render_html(db.get("c_harold"))
    for s in ("1. Leave early", "2. If no one comes", "3. If you cannot move", "4. Your devices", "5. For whoever comes",
              "Grace Kim (sister)", "Your oxygen battery lasts about 4 hours", "Charge your chair every night",
              "Reviewed by", "Dana", "data:image/png;base64", "Keypad by the garage"):
        assert s in html, s
    assert html.count("<polyline") >= 2          # route drawn on the satellite thumbnail(s)
    # the ranking terms are for the reviewer, not for whoever picks the client up: preview only
    assert "of 100" not in html and "Claude, satellite photo" not in html
    preview = pdf.render_html(db.get("c_harold"), for_print=False)
    assert "of 100" in preview and "Claude, satellite photo" in preview


def test_bedbound_card(sample):
    from ember_staff import db, pdf
    html = pdf.render_html(db.get("c_walter"))
    assert "Moving you needs trained help" in html and "3. If you cannot move" in html
    assert "Your ventilator battery lasts about 8 hours" in html


def test_bilingual_card_shows_both_languages(sample):
    from ember_staff import db, pdf
    row = db.get("c_lupe")
    row["text"] = {"language": "Spanish", "sections": {
        "steps_en": ["Start on Maxwell Drive.", "Turn left onto Clark Road."],
        "steps_l2": ["Empiece en Maxwell Drive.", "Gire a la izquierda en Clark Road."],
        "shelter_en": ["Close the doors."], "shelter_l2": ["Cierre las puertas."]}}
    html = pdf.render_html(row)
    assert "Empiece en Maxwell Drive." in html and "Start on Maxwell Drive." in html
    assert "Cierre las puertas." in html and "Close the doors." in html
    assert html.index("Empiece en Maxwell Drive.") < html.index("Start on Maxwell Drive.")


def test_thumb_route_never_under_outline_or_start_dot():
    """Owner map rule on the printed thumb: the route stops short of the green refuge outline and of the Start dot."""
    from ember_staff import card
    ring = [(300.0, 300.0), (400.0, 300.0), (400.0, 400.0), (300.0, 400.0)]
    pts = [(40.0, 40.0), (200.0, 200.0), (350.0, 350.0)]
    drawn = card.trim_to_outline(pts, ring, clearance=25.6)
    assert drawn[-1] != pts[-1] and not card._inside(drawn[-1], ring)
    assert all(not card._inside(p, ring) for p in drawn)
    started = card.trim_start(drawn, 52.0)
    assert started[0] != pts[0] and abs(((started[0][0] - 40) ** 2 + (started[0][1] - 40) ** 2) ** 0.5 - 52.0) < 0.2


def test_thumb_inset_sits_below_the_photo(sample):
    from ember_staff import db, pdf
    html = pdf.render_html(db.get("c_margaret"))
    if 'class="insetbox"' in html:
        assert html.index('</div>', html.index('class="imgbox"')) < html.index('class="insetbox"')
