"""Apify county-fire-situation feed: 2 s timeout, cached last result, age shown, 'no feed' when unset."""
import time

import httpx
import pytest

SITUATION = [{"county": "fake", "fetched_at": "2026-10-23T12:00:00Z", "incidents": [], "closures": [],
              "zones": [{"id": "PAR-E004", "status": "warning", "updated": "2026-10-23T11:50:00Z"}],
              "outages": [{"area": "ZIP 95969", "kind": "psps", "est_restore": "2026-10-24T08:00Z"}]}]


class FakeHTTP:
    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, timeout, headers))
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json=SITUATION, request=httpx.Request("GET", url))


def test_no_feed_when_unset(env):
    from ember_staff import feed
    assert feed.get_feed()["state"] == "none"


def test_timeout_without_cache(env, monkeypatch):
    from ember_staff import feed
    monkeypatch.setenv("APIFY_SITUATION_DATASET_ID", "ds1")
    f = feed.get_feed(client=FakeHTTP("timeout"))
    assert f["state"] == "error" and "Timeout" in f["error"]


def test_live_then_timeout_uses_cache(env, monkeypatch):
    from ember_staff import config, feed
    monkeypatch.setenv("APIFY_SITUATION_DATASET_ID", "ds1")
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    http = FakeHTTP("ok")
    f = feed.get_feed(client=http)
    url, timeout, headers = http.calls[0]
    assert url == "https://api.apify.com/v2/datasets/ds1/items" and timeout == 2.0
    assert headers["Authorization"] == "Bearer tok"
    assert f["state"] == "live" and config.feed_cache_path().exists()
    assert feed.zone_status(f["situation"], "PAR-E004") == "warning"
    assert feed.outage_for(f["situation"], {"zip": "95969"})["kind"] == "psps"
    # make the cache old, then the network times out: cached answer + its age
    import json
    c = json.loads(config.feed_cache_path().read_text())
    c["fetched_ts"] = time.time() - 3 * 3600
    config.feed_cache_path().write_text(json.dumps(c))
    f2 = feed.get_feed(client=FakeHTTP("timeout"))
    assert f2["state"] == "cached" and f2["situation"]["zones"][0]["id"] == "PAR-E004"
    assert feed.age_text(f2["age_s"]) == "3 h ago"


def test_clients_list_shows_zone_and_outage(app_client, sample, monkeypatch):
    from ember_staff import feed
    monkeypatch.setenv("APIFY_SITUATION_DATASET_ID", "ds1")
    monkeypatch.setattr(feed.httpx, "get", FakeHTTP("ok").get)
    html = app_client.get("/").text
    assert "fire situation from just now" in html
    assert 'class="badge warning">warning' in html and "psps" in html
    monkeypatch.setattr(feed.httpx, "get", FakeHTTP("timeout").get)
    html = app_client.get("/?x=1").text
    assert "warning" in html          # within MIN_REFRESH_S the cache is used without a call
