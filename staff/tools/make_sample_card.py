"""Generate staff/out/sample_card.pdf (+ page PNGs) from the fake bundle, using a throwaway database.

    .venv/bin/python staff/tools/make_sample_card.py [client_id_from_sample_csv ...]

Default client: c_rosa (manual chair, Spanish). Uses Claude for the text only if ANTHROPIC_API_KEY is set.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

STAFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAFF))
os.environ.setdefault("EMBER_DATA_DIR", tempfile.mkdtemp(prefix="ember_sample_"))
os.environ.setdefault("EMBER_COUNTY", "fake")

from ember_staff import db, pdf, profiles, workflow  # noqa: E402


def main(ids):
    ps, errs = profiles.from_csv((STAFF / "sample_registry.csv").read_text())
    assert not errs, errs
    for p in ps:
        db.upsert_profile(p)
    out = STAFF / "out"
    out.mkdir(exist_ok=True)
    for i, cid in enumerate(ids):
        workflow.run_engine(cid, use_claude=True)
        workflow.stamp(cid, "Sample Reviewer", attested=True)
        data, pages, level = pdf.render_pdf(db.get(cid))
        name = "sample_card.pdf" if i == 0 else f"sample_card_{cid}.pdf"
        (out / name).write_bytes(data)
        print(f"{out / name}: {pages} pages, layout level {level}")
        if sys.platform == "darwin":
            subprocess.run([sys.executable, str(STAFF / "tools" / "pdf_to_png.py"), str(out / name)], check=False)


if __name__ == "__main__":
    main(sys.argv[1:] or ["c_rosa"])
