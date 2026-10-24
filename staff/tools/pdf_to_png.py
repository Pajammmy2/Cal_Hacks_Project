"""Render each page of a PDF to PNG for a visual check (macOS sips; no poppler needed).

    python staff/tools/pdf_to_png.py card.pdf [out_prefix]
"""
import io
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main(pdf, prefix=None):
    pdf = Path(pdf)
    prefix = prefix or str(pdf.with_suffix(""))
    out = []
    for i, page in enumerate(PdfReader(str(pdf)).pages, 1):
        w = PdfWriter()
        w.add_page(page)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            w.write(f)
        png = f"{prefix}_p{i}.png"
        subprocess.run(["sips", "-s", "format", "png", "-Z", "1600", f.name, "--out", png], check=True, capture_output=True)
        out.append(png)
    print("\n".join(out))


if __name__ == "__main__":
    main(*sys.argv[1:])
