from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
FAKE = ROOT / "bundles" / "fake"


@pytest.fixture(scope="module")
def client():
    if not FAKE.exists():
        import subprocess, sys
        subprocess.check_call([sys.executable, str(ROOT / "engine" / "fixtures" / "make_fake_bundle.py")])
    import serve
    serve.BUNDLES = ROOT / "bundles"
    return TestClient(serve.app)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] and "fake" in r.json()["bundles"]


def test_manifest(client):
    r = client.get("/bundles/fake/manifest")
    assert r.status_code == 200 and r.json()["county"] == "fake"
    assert client.get("/bundles/nope/manifest").status_code == 404
    assert client.get("/bundles/..%2Fetc/manifest").status_code in (400, 404)


def test_plan_and_blocked(client):
    body = {"county": "fake", "address": "1500 Pearson Rd", "profile": {"mobility": "manual_chair"}, "client_id": "c_1"}
    r = client.post("/plan", json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["client_id"] == "c_1" and p["county"] == "fake" and p["choices"]
    first_edge = p["choices"][0]["route"]["edges"][0]
    r2 = client.post("/plan", json=dict(body, blocked=[first_edge]))
    assert r2.status_code == 200
    for c in r2.json()["choices"]:
        assert first_edge not in c["route"]["edges"]


def test_plan_errors(client):
    assert client.post("/plan", json={"county": "fake", "address": "no such place",
                                      "profile": {"mobility": "walker"}}).status_code == 422
    assert client.post("/plan", json={"county": "fake", "address": "1500 Pearson Rd",
                                      "profile": {"mobility": "rocket"}}).status_code == 422
    assert client.post("/plan", json={"county": "fake", "address": "1500 Pearson Rd",
                                      "profile": {"mobility": "walker"}, "blocked": [10 ** 9]}).status_code == 422
    assert client.post("/plan", json={"county": "nope", "address": "x",
                                      "profile": {"mobility": "walker"}}).status_code == 404


def test_bedbound_plan(client):
    r = client.post("/plan", json={"county": "fake", "address": "1500 Pearson Rd", "profile": {"mobility": "bedbound"}})
    assert r.status_code == 200 and r.json()["no_route"] is True
