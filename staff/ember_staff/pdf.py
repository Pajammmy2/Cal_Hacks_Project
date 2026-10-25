"""HTML -> PDF with headless Chromium (Playwright). Letter, one sheet front and back (exactly 2 pages).

If the card runs long we tighten spacing and image sizes level by level; we never shrink the fonts.
"""
import io

from . import card
from .templating import templates

MAX_TIGHTEN = len(card.LEVELS) - 1


class CardTooLong(Exception):
    pass


def render_html(row, tighten=0, for_print=True):
    return templates.get_template("card.html").render(**card.context(row, tighten=tighten, for_print=for_print))


def page_count(pdf_bytes):
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def html_to_pdf(html, page=None):
    def go(pg):
        pg.set_content(html, wait_until="load")
        return pg.pdf(format="Letter", print_background=True, prefer_css_page_size=True)
    if page is not None:
        return go(page)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            return go(browser.new_page())
        finally:
            browser.close()


def render_pdf(row, allow_long=False):
    """Returns (pdf_bytes, pages, tighten_level). Raises CardTooLong if even the tightest layout exceeds 2 pages,
    unless allow_long: then the tightest layout is returned with its real page count (a 3-page card beats no card)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            last = None
            for level in range(MAX_TIGHTEN + 1):
                pdf = html_to_pdf(render_html(row, tighten=level), page)
                n = page_count(pdf)
                last = (pdf, n, level)
                if n <= 2:
                    return last
        finally:
            browser.close()
    if allow_long:
        return last
    raise CardTooLong(f"Card needs {last[1]} pages even with the tightest spacing. Shorten the text (edit sentences).")
