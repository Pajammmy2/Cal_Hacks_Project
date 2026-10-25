"""Printed card: Letter, exactly one sheet front and back, fonts never shrink."""
import io
import re

import pytest
from pypdf import PdfReader


def _stamp(cid):
    from ember_staff import workflow
    workflow.stamp(cid, "Dana", attested=True)


@pytest.mark.parametrize("cid", ["c_rosa", "c_harold", "c_margaret", "c_walter", "c_june", "c_lupe"])
def test_pdf_is_letter_with_exactly_two_pages(sample, cid):
    from ember_staff import db, pdf
    _stamp(cid)
    data, pages, level = pdf.render_pdf(db.get(cid))
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 2 == pages
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        assert (round(w), round(h)) == (612, 792)          # US Letter in points


@pytest.mark.parametrize("cid,body", [("c_rosa", 18), ("c_margaret", 22), ("c_june", 22)])
def test_type_sizes_never_shrink(sample, cid, body):
    from ember_staff import db, pdf
    row = db.get(cid)
    for level in range(pdf.MAX_TIGHTEN + 1):
        html = pdf.render_html(row, tighten=level)
        assert f"font-size: {body}pt" in html
        assert "font-size: 28pt" in html
        sizes = [int(s) for s in re.findall(r"font-size:\s*(\d+)pt", html)]
        assert min(sizes) >= body


def test_card_content(sample):
    from ember_staff import db, pdf
    _stamp("c_harold")
    html = pdf.render_html(db.get("c_harold"))
    for s in ("1. Leave early", "2. If no one comes", "3. If you cannot move", "4. Your devices", "5. For whoever comes",
              "Grace Kim (sister)", "Your oxygen battery lasts about 4 hours", "Charge your chair every night",
              "Reviewed by", "Dana", "data:image/png;base64", "Keypad by the garage"):
        assert s in html, s
    assert html.count("<polyline") >= 4          # route drawn on both satellite thumbnails
    # the ranking terms are for the reviewer, not for whoever picks the client up: preview only
    assert "score" not in html and "Claude, satellite photo" not in html
    preview = pdf.render_html(db.get("c_harold"), for_print=False)
    assert "score" in preview and "Claude, satellite photo" in preview


def test_bedbound_card(sample):
    from ember_staff import db, pdf
    html = pdf.render_html(db.get("c_walter"))
    assert "Moving you needs trained help" in html and "3. If you cannot move" in html
    assert "Your ventilator battery lasts about 8 hours" in html
