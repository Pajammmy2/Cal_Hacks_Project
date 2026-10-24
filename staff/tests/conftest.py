import shutil
import sys
from pathlib import Path

import pytest

STAFF = Path(__file__).resolve().parents[1]
REPO = STAFF.parent
sys.path.insert(0, str(STAFF))

SECRET_ENV = ("ANTHROPIC_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "APIFY_TOKEN", "APIFY_SITUATION_DATASET_ID",
              "EMBER_ENGINE_URL", "EMBER_PASSPHRASE", "EMBER_ALERT_LINE")


@pytest.fixture(scope="session")
def bundles_copy(tmp_path_factory):
    """A private copy of bundles/fake so printing and audio never touch the real bundle."""
    src = REPO / "bundles" / "fake"
    if not (src / "graph.json").exists():
        import subprocess
        subprocess.run([sys.executable, str(REPO / "engine" / "fixtures" / "make_fake_bundle.py")], check=True)
    root = tmp_path_factory.mktemp("bundles")
    shutil.copytree(src, root / "fake", ignore=shutil.ignore_patterns("*.mp3"))
    (root / "fake" / "audio" / "index.json").write_text("{}")
    for p in (root / "fake" / "plans").glob("*.json"):
        p.unlink()
    return root


@pytest.fixture
def env(tmp_path, monkeypatch, bundles_copy):
    for k in SECRET_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EMBER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBER_BUNDLES_DIR", str(bundles_copy))
    monkeypatch.setenv("EMBER_COUNTY", "fake")
    return tmp_path


@pytest.fixture
def app_client(env):
    from fastapi.testclient import TestClient
    from ember_staff.app import create_app
    return TestClient(create_app())


@pytest.fixture
def sample(env):
    """The six sample-registry clients, imported and planned with templated text."""
    from ember_staff import db, profiles, workflow
    ps, errs = profiles.from_csv((STAFF / "sample_registry.csv").read_text())
    assert not errs
    for p in ps:
        db.upsert_profile(p)
    workflow.run_all()
    return {p["id"]: p for p in ps}
